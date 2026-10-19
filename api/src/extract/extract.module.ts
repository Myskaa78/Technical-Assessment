import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { ExtractController } from './extract.controller';
import { ExtractService } from './extract.service';

@Module({
  imports: [HttpModule],
  controllers: [ExtractController],
  providers: [ExtractService],
  exports: [ExtractService],
})
export class ExtractModule {}

