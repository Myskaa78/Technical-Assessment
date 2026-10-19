import {
  Injectable,
  Logger,
  HttpException,
  HttpStatus,
  Inject,
} from '@nestjs/common';
import { HttpService } from '@nestjs/axios';
import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Cache } from 'cache-manager';
import { firstValueFrom } from 'rxjs';
import { ExtractDto } from './dto/extract.dto';

export interface MediaImage {
  url: string;
  alt?: string | null;
}

export interface MediaVideo {
  url: string;
  type: string;
}

export interface ScrapeMetadata {
  author?: string | null;
  publishedAt?: string | null;
  language?: string | null;
  [key: string]: any;
}

export interface ScraperResponse {
  url: string;
  title?: string | null;
  description?: string | null;
  text: string;
  images: MediaImage[];
  videos: MediaVideo[];
  metadata: ScrapeMetadata;
}

export interface ExtractResult extends ScraperResponse {
  extractedAt: string;
  cached: boolean;
  dynamic?: boolean;
}

@Injectable()
export class ExtractService {
  private readonly logger = new Logger(ExtractService.name);
  private readonly scraperServiceUrl =
    process.env.SCRAPER_URL || 'http://localhost:8000/scrape';
  // Cache TTL configurable via variable d'environnement (défaut : 1h = 3600000 ms)
  private readonly cacheTtlMs = parseInt(
    process.env.CACHE_TTL_MS || '3600000',
    10,
  );

  constructor(
    private readonly httpService: HttpService,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
  ) {}

  async extract(extractDto: ExtractDto): Promise<ExtractResult> {
    const { url } = extractDto;
    // le rendu dynamique JS by default, si dynamic est desactiver
    const isDynamic = extractDto.dynamic !== undefined ? Boolean(extractDto.dynamic) : true;

    const cacheKey = `${url}:dynamic=${isDynamic}`;

    const cachedData = await this.cacheManager.get<ExtractResult>(cacheKey);
    if (cachedData) {
      this.logger.log(`Cache HIT pour: ${cacheKey}`);
      return {
        ...cachedData,
        cached: true,
      };
    }

    this.logger.log(
      `Cache MISS pour: ${cacheKey}. Appel vers le microservice Python (${this.scraperServiceUrl}) [dynamic=${isDynamic}]...`,
    );

    const requestTimeout = isDynamic ? 25000 : 15000;
    let scraperData: ScraperResponse;
    try {
      const response = await firstValueFrom(
        this.httpService.post<ScraperResponse>(
          this.scraperServiceUrl,
          { url, dynamic: isDynamic },
          { timeout: requestTimeout },
        ),
      );
      scraperData = response.data;
    } catch (error: any) {
      this.logger.error(
        `Erreur lors de l'appel au service Python (${this.scraperServiceUrl}): ${error.message}`,
      );

      const statusFromScraper = error.response?.status;
      const detailFromScraper = error.response?.data?.detail;

      if (statusFromScraper && detailFromScraper) {
        throw new HttpException(
          {
            statusCode: statusFromScraper,
            message: detailFromScraper,
            error: 'ScraperClientError',
          },
          statusFromScraper,
        );
      }

      throw new HttpException(
        {
          statusCode: HttpStatus.INTERNAL_SERVER_ERROR,
          message:
            'Le microservice de scraping Python (port 8000) est inaccessible ou a retourné une erreur.',
          error: 'ScraperServiceUnavailable',
          details: error.message,
        },
        HttpStatus.INTERNAL_SERVER_ERROR,
      );
    }

    const extractedAt = new Date().toISOString();
    const result: ExtractResult = {
      ...scraperData,
      extractedAt,
      cached: false,
      dynamic: isDynamic,
    };

    await this.cacheManager.set(cacheKey, result, this.cacheTtlMs);
    this.logger.log(`Données sauvegardées dans le cache pour: ${cacheKey} (TTL: 1h)`);

    return result;
  }
}
