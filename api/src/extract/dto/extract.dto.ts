import { IsNotEmpty, IsUrl } from 'class-validator';

export class ExtractDto {
  @IsNotEmpty({ message: "L'URL est requise." })
  @IsUrl(
    { require_protocol: true },
    { message: "L'URL doit être valide et débuter par http:// ou https://." },
  )
  url: string;
}

