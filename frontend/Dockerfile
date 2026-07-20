# --- Build stage -----------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

# Vite inlines VITE_* variables at build time, so they arrive as build args.
ARG VITE_CHAT_PROVIDER=mock
ARG VITE_CHAINLIT_URL=http://localhost:8000
ENV VITE_CHAT_PROVIDER=${VITE_CHAT_PROVIDER} \
    VITE_CHAINLIT_URL=${VITE_CHAINLIT_URL}

RUN npm run build

# --- Runtime stage ----------------------------------------------------------
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
