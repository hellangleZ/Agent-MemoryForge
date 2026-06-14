const iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="8" fill="#111111"/>
  <path d="M9 10.5h14M9 16h14M9 21.5h14" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>
  <circle cx="9" cy="10.5" r="2" fill="#ffffff"/>
  <circle cx="23" cy="16" r="2" fill="#ffffff"/>
  <circle cx="9" cy="21.5" r="2" fill="#ffffff"/>
</svg>`;

export function GET() {
  return new Response(iconSvg, {
    headers: {
      'content-type': 'image/svg+xml; charset=utf-8',
      'cache-control': 'public, max-age=86400',
    },
  });
}
