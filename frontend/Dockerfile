FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# template 交由 nginx 入口 envsubst 注入 MCP_TOKEN（容器环境变量）
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
