import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Locally, do what nginx does in production: /config.json → sites/<host>.json.
// localhost uses DEV_SITE (default below); any other host uses its own file.
const DEV_SITE = process.env.DEV_SITE || 'checkout.mastertherapy.example';

function siteConfigPlugin() {
  const middleware = (dir) => (req, res, next) => {
    if (!req.url || !/^\/config\.json(\?|$)/.test(req.url)) return next();
    const host = String(req.headers.host || '').replace(/:\d+$/, '').toLowerCase();
    const name = host === 'localhost' ? DEV_SITE : host;
    const file = path.join(dir, 'sites', `${name}.json`);
    if (!/^[a-z0-9.-]+$/.test(name) || !fs.existsSync(file)) {
      res.statusCode = 404;
      res.end('Not found');
      return;
    }
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    fs.createReadStream(file).pipe(res);
  };
  return {
    name: 'site-config-by-host',
    configureServer(server) {
      server.middlewares.use(middleware(path.resolve('public')));
    },
    configurePreviewServer(server) {
      server.middlewares.use(middleware(path.resolve('dist')));
    },
  };
}

export default defineConfig({
  // Relative asset paths: dist/ works at the web root or in any subfolder.
  base: './',
  plugins: [react(), siteConfigPlugin()],
  server: { port: 5173 },
});
