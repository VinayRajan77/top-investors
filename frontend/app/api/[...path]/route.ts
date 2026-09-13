import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

function apiBase() {
  // A public Render API URL is reliable from browser and server runtimes.
  // Use the private host only as a fallback for environments that provide it.
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (process.env.API_PROXY_HOST) return `http://${process.env.API_PROXY_HOST}`;
  return 'http://localhost:8000';
}

async function forward(request: NextRequest, { params }: { params: { path: string[] } }) {
  const target = new URL(`/api/${params.path.join('/')}`, apiBase());
  target.search = request.nextUrl.search;
  const response = await fetch(target, {
    method: request.method,
    headers: request.headers.get('x-admin-token') ? { 'x-admin-token': request.headers.get('x-admin-token')! } : undefined,
    cache: 'no-store',
  });
  const headers = new Headers();
  const contentType = response.headers.get('content-type');
  if (contentType) headers.set('content-type', contentType);
  return new Response(response.body, { status: response.status, headers });
}

export async function GET(request: NextRequest, context: { params: { path: string[] } }) { return forward(request, context); }
export async function POST(request: NextRequest, context: { params: { path: string[] } }) { return forward(request, context); }
