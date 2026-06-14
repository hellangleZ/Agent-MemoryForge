FROM node:20-alpine

WORKDIR /app

ENV HOST=0.0.0.0 \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE= \
    PORTAL_API_PROXY_TARGET=http://gateway:8080

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build
RUN npm prune --omit=dev

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start:prod"]
