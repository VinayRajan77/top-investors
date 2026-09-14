import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = { title: 'Top Investors', description: 'Explore reported 13F portfolios' };
export default function Layout({children}:{children:React.ReactNode}) { 
  return (
    <html lang="en">
      <body>
        <div className="bg-amber-50 border-b border-amber-200 text-amber-800 px-4 py-2 text-center text-sm font-medium">
          Note: Portfolio values currently displayed with a "T" suffix are reported in Billions ($B).
        </div>
        {children}
      </body>
    </html>
  );
}
