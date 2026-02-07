FROM node:20-alpine

WORKDIR /app/apps/builder

COPY apps/builder/package.json apps/builder/package-lock.json ./
RUN npm ci

COPY apps/builder ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
