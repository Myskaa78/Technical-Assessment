import {
  Controller,
  Post,
  Body,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { ExtractService } from './extract.service';
import { ExtractDto } from './dto/extract.dto';

@Controller('api')
export class ExtractController {
  constructor(private readonly extractService: ExtractService) {}

  // call pour le futur route du service de scrap python
  @Post('extract')
  @HttpCode(HttpStatus.OK)
  async extract(@Body() extractDto: ExtractDto) {
    return this.extractService.extract(extractDto);
  }
}

