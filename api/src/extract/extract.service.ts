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

export interface ScraperResponse {
  url: string;
  title: string;
  description: string;
  text: string;
  images: string[];
  videos: string[];
  metadata: Record<string, any>;
}

export interface ExtractResult extends ScraperResponse {
  extractedAt: string;
  cached: boolean;
}

@Injectable()
export class ExtractService {
  private readonly logger = new Logger(ExtractService.name);
  private readonly scraperServiceUrl =
    process.env.SCRAPER_URL || 'http://localhost:8000/scrape';
  // Cache de 1 heure 
  private readonly cacheTtlMs = 60 * 60 * 1000;

  constructor(
    private readonly httpService: HttpService,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
  ) {}


  // verification si l'url est deja enregistrer dans le cache 
  async extract(extractDto: ExtractDto): Promise<ExtractResult> {
    const { url } = extractDto;

    const cachedData = await this.cacheManager.get<ExtractResult>(url);
    if (cachedData) {
      this.logger.log(`Cache HIT pour: ${url}`);
      return {
        ...cachedData,
        cached: true,
      };
    }

    this.logger.log(`Cache MISS pour: ${url}. Appel vers le service Scrap (${this.scraperServiceUrl})...`);


    // Call vers axios pour le scrap service

    let scraperData: ScraperResponse;
    try {
      const response = await firstValueFrom(
        this.httpService.post<ScraperResponse>(
          this.scraperServiceUrl,
          { url },
          { timeout: 5000 },
        ),
      );
      scraperData = response.data;
    } catch (error: any) {
      this.logger.error(
        `Erreur lors de l'appel au service Python (${this.scraperServiceUrl}): ${error.message}`,
      );
      throw new HttpException(
        {
          statusCode: HttpStatus.INTERNAL_SERVER_ERROR,
          message:
            'Le service de scrap Python est inaccessible ou a retourné une erreur',
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
    };

    // Save dans le cache 1h
    await this.cacheManager.set(url, result, this.cacheTtlMs);
    this.logger.log(`Données sauvegardées dans le cache pour: ${url} (TTL: 1h)`);


    return result;
  }
}

