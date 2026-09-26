FROM node:22-alpine AS build
WORKDIR /app
COPY studio-ui/package.json studio-ui/package-lock.json* ./
RUN npm install
COPY studio-ui/index.html studio-ui/vite.config.js ./
COPY studio-ui/src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY studio-ui/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY studio-ui/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
ENTRYPOINT ["/docker-entrypoint.sh"]
