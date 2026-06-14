# Agent-MemoryForge Portal - Modern Next.js UI

A modern, production-ready portal UI for Agent-MemoryForge, built with Next.js 14, Tailwind CSS, and Framer Motion.

## Features

- 🎨 **Modern Design System** - Beautiful dark theme with glassmorphism effects
- ⚡ **Next.js 14** - App Router, Server Components, and optimized performance
- 🎭 **Framer Motion** - Smooth animations and transitions
- 📱 **Responsive** - Mobile-first design
- 🔗 **Full API Integration** - All Python portal features preserved
- 🎯 **TypeScript** - Full type safety
- 🌐 **Public Access** - Configurable for public network access

## Quick Start

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

```bash
# Navigate to portal directory
cd portal-ui

# Install dependencies
npm install

# Start development server (公网访问)
npm run dev

# 或者指定host和端口
HOST=0.0.0.0 PORT=3000 npm run dev:custom
```

### Production Mode (公网访问)

```bash
# Build first
npm run build

# Start production server (公网访问)
npm start

# 或者自定义host和端口
HOST=0.0.0.0 PORT=3000 npm run start:prod
```

The portal will be available at:
- **Local**: http://localhost:3000
- **Public**: http://YOUR_IP:3000

## Environment Variables

Create a `.env.local` file in the portal-ui directory:

```env
# API Gateway URL (default: local gateway)
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080

# Portal listen host (0.0.0.0 for public access)
HOST=0.0.0.0

# Portal listen port
PORT=3000
```

## Project Structure

```
portal-ui/
├── src/
│   ├── app/                    # Next.js App Router pages
│   │   ├── page.tsx            # Customer portal home
│   │   ├── login/              # Login page
│   │   ├── chat/[agent]/       # Chat interface
│   │   └── admin/              # Admin portal pages
│   │       ├── page.tsx        # Admin home
│   │       └── chat/[agent]/   # Admin chat
│   ├── components/
│   │   ├── ui/                 # Reusable UI components
│   │   │   ├── Button.tsx
│   │   │   ├── Card.tsx
│   │   │   ├── Input.tsx
│   │   │   ├── Badge.tsx
│   │   │   └── Toast.tsx
│   │   ├── Sidebar.tsx         # Navigation sidebar
│   │   └── ChatWindow.tsx      # Chat interface
│   └── lib/
│       ├── api.ts              # API client
│       └── utils.ts            # Utility functions
├── tailwind.config.ts          # Tailwind configuration
├── next.config.js              # Next.js configuration (公网访问配置)
└── README.md
```

## Customer Portal

| Route | Description |
|-------|-------------|
| `/` | Welcome page with features overview |
| `/login` | User authentication |
| `/signup` | Account creation |
| `/workspace` | Workspace management |
| `/config` | Configuration settings |
| `/chat/[agent]` | Chat interface (e.g., /chat/code-assistant) |
| `/profile` | User profile |
| `/tools` | MCP tools list |

## Admin Portal

| Route | Description |
|-------|-------------|
| `/admin` | Admin dashboard |
| `/admin/login` | Admin authentication |
| `/admin/signup` | Admin signup |
| `/admin/workspaces` | Workspace management |
| `/admin/chat/[agent]` | Admin chat interface |
| `/admin/memory` | Memory inspection |
| `/admin/runs` | Trace debugging |
| `/admin/monitoring` | System monitoring |
| `/admin/tools` | MCP tools |
| `/admin/agents` | Agent discovery |
| `/admin/me` | Profile management |

## API Integration

The portal communicates with the backend gateway at `http://127.0.0.1:8080` (configurable via `NEXT_PUBLIC_API_BASE`).

All Python portal API endpoints are preserved:
- `POST /portal/v1/login` - Authentication
- `POST /portal/v1/signup` - Registration
- `GET/POST /portal/v1/workspace/config` - Workspace configuration
- `POST /v1/chat` - Chat API
- `GET /v1/agents` - Agent discovery
- `GET /portal/v1/tools` - MCP tools

## Public Network Access

### Configure Firewall

Make sure port 3000 is open on your server:

```bash
# Ubuntu/Debian
sudo ufw allow 3000

# CentOS/RHEL
sudo firewall-cmd --add-port=3000/tcp --permanent
sudo firewall-cmd --reload
```

### Run Behind Nginx (Recommended)

Create nginx config `/etc/nginx/sites-available/portal`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/portal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Docker Deployment

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:18-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.js ./
COPY --from=builder /app/package*.json ./
ENV HOST=0.0.0.0
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "start"]
```

Run with Docker:

```bash
docker build -t agent-memoryforge-portal .
docker run -d -p 3000:3000 -e HOST=0.0.0.0 agent-memoryforge-portal
```

## Styling

The design system uses:
- **Tailwind CSS** for utility classes
- **Custom CSS variables** for theming
- **Framer Motion** for animations

### Color Palette

| Color | Hex | Usage |
|-------|-----|-------|
| Brand Purple | `#6366f1` | Primary actions, brand elements |
| Cyan | `#22d3ee` | Accents, success states |
| Green | `#10b981` | Positive actions, online status |
| Amber | `#f59e0b` | Warnings, pending states |
| Red | `#ef4444` | Errors, destructive actions |
| Background | `#0a0a0f` | Main background |

## Development

### Adding New Pages

1. Create a new directory in `src/app/`
2. Add `page.tsx` with the page component
3. Update the sidebar navigation if needed

### Adding Components

1. Create component in `src/components/ui/`
2. Use the component in pages
3. Add proper TypeScript types

## Deployment Options

### Option 1: Direct Run (Simple)

```bash
cd portal-ui
npm install
HOST=0.0.0.0 PORT=3000 npm run dev
```

### Option 2: PM2 Process Manager

```bash
npm install -g pm2
pm2 start npm --name "portal" -- run dev --prefix /path/to/portal-ui -- -H 0.0.0.0 -p 3000
pm2 save
pm2 startup
```

### Option 3: Docker Compose

```yaml
version: '3.8'
services:
  portal:
    build: ./portal-ui
    ports:
      - "3000:3000"
    environment:
      - HOST=0.0.0.0
      - PORT=3000
      - NEXT_PUBLIC_API_BASE=http://gateway:8080
    restart: unless-stopped
```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 3000
sudo lsof -i :3000

# Kill the process
sudo kill -9 PID
```

### Cannot Access from External Network

1. Check if server is listening on 0.0.0.0:
   ```bash
   netstat -tulpn | grep 3000
   ```

2. Check firewall settings
3. Verify cloud provider security groups (AWS, GCP, Azure)

### API Connection Failed

Ensure the backend gateway is running and `NEXT_PUBLIC_API_BASE` is set correctly in `.env.local`.

## License

MIT
