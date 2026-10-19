import { NestFactory } from '@nestjs/core';
import { ValidationPipe, Logger } from '@nestjs/common';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { AppModule } from './app.module';

let loadedEnvFile: string | null = null;

// Check si le .env est present (racine ou api) 
function loadEnv() {
  const candidatePaths = [
    join(process.cwd(), '.env'),
    join(process.cwd(), '..', '.env'),
    join(__dirname, '..', '.env'),
  ];
  for (const envPath of candidatePaths) {
    if (existsSync(envPath)) {
      loadedEnvFile = envPath;
      const content = readFileSync(envPath, 'utf8');
      for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (trimmed && !trimmed.startsWith('#')) {
          const [key, ...rest] = trimmed.split('=');
          const trimmedKey = key.trim();
          if (trimmedKey && !process.env[trimmedKey]) {
            process.env[trimmedKey] = rest.join('=').trim().replace(/^["']|["']$/g, '');
          }
        }
      }
      break;
    }
  }
}

loadEnv();

async function bootstrap() {
  const logger = new Logger('Bootstrap');
  const app = await NestFactory.create(AppModule);

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      transform: true,
    }),
  );

  if (loadedEnvFile) {
    logger.log(`Fichier .env chargé : ${loadedEnvFile}`);
  } else {
    logger.log(`Aucun fichier .env trouvé (valeurs par défaut actives)`);
  }

  const port = process.env.PORT || 3000;
  await app.listen(port);

  logger.log(`la gateway et Frontend a commncer sur http://localhost:${port}`);
}

bootstrap();

