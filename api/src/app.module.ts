import { Module } from '@nestjs/common';
import { CacheModule } from '@nestjs/cache-manager';
import { ServeStaticModule } from '@nestjs/serve-static';
import { join } from 'path';
import { existsSync } from 'fs';
import { ExtractModule } from './extract/extract.module';

// Trouver le dossier Public, racine ou pas 
function resolvePublicPath(): string {
  const cwdPublic = join(process.cwd(), 'public');
  if (existsSync(cwdPublic)) {
    return cwdPublic;
  }
  const relDistPublic = join(__dirname, '..', 'public');
  if (existsSync(relDistPublic)) {
    return relDistPublic;
  }
  return join(__dirname, '..', '..', 'public');
}

@Module({
  imports: [
    CacheModule.register({
      isGlobal: true,
      ttl: 3600 * 1000,
    }),
    ServeStaticModule.forRoot({
      rootPath: resolvePublicPath(),
      exclude: ['/api/(.*)'],
    }),
    ExtractModule,
  ],
})
export class AppModule {}

