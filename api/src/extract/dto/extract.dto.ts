import { IsNotEmpty, IsUrl, IsOptional, IsBoolean } from 'class-validator';

export class ExtractDto {
  @IsNotEmpty({ message: "L'URL est requise." })
  @IsUrl(
    { require_protocol: true },
    { message: "L'URL doit être valide et débuter par http:// ou https://." },
  )
  url: string;

  @IsOptional()
  @IsBoolean({ message: 'Le paramètre dynamic doit être un booléen.' })
  dynamic?: boolean;
}
