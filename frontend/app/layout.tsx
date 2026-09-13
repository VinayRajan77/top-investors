import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = { title: 'Top Investors', description: 'Explore reported 13F portfolios' };
export default function Layout({children}:{children:React.ReactNode}) { return <html lang="en"><body>{children}</body></html> }
