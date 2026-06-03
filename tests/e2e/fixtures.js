const { test: base, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const test = base.extend({
  djangoServer: [async ({}, use, workerInfo) => {
    const port = 3101 + workerInfo.workerIndex;
    const dbPath = `/tmp/e2e_${workerInfo.workerIndex}.sqlite3`;
    const baseURL = `http://127.0.0.1:${port}`;

    const env = {
      ...process.env,
      PLAYWRIGHT_PORT: String(port),
      DATABASE_URL: `sqlite://${dbPath}`,
      DJANGO_ALLOWED_HOSTS: '127.0.0.1,localhost',
      DJANGO_DEBUG: '1',
      DJANGO_SECRET_KEY: 'test_sk_playwright_local_only',
    };

    const serverProcess = spawn('bash', ['scripts/start-e2e.sh'], { env, cwd: process.cwd() });

    // Wait for server to be ready
    await new Promise((resolve) => {
      let resolved = false;
      serverProcess.stdout.on('data', (data) => {
        if (!resolved && data.toString().includes('Starting development server at')) {
          resolved = true;
          resolve();
        }
      });
      // Fallback
      setTimeout(() => { if(!resolved){ resolved=true; resolve(); } }, 5000);
    });

    await use(baseURL);

    serverProcess.kill();
    // Cleanup DB
    if (fs.existsSync(dbPath)) {
      fs.unlinkSync(dbPath);
    }
  }, { scope: 'worker' }],

  baseURL: async ({ djangoServer }, use) => {
    await use(djangoServer);
  }
});

exports.test = test;
exports.expect = expect;
