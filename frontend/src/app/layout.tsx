import type { Metadata, Viewport } from 'next';
import './globals.css';
import MobileNavigation from '@/components/MobileNavigation';

export const metadata: Metadata = {
  title: 'Умный Календарь',
  description: 'Веб-приложение для управления событиями и задачами',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  interactiveWidget: 'resizes-content',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        {children}
        <MobileNavigation />
      </body>
    </html>
  );
}
