const { test: base, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');

function waitForHttpServer(baseURL, serverProcess) {
  const deadline = Date.now() + 30_000;

  return new Promise((resolve, reject) => {
    let settled = false;

    const finish = (callback, value) => {
      if (settled) {
        return;
      }
      settled = true;
      serverProcess.off('exit', handleExit);
      callback(value);
    };

    const handleExit = (code, signal) => {
      finish(reject, new Error(`Django E2E server exited before readiness. code=${code} signal=${signal}`));
    };

    const poll = () => {
      const request = http.get(baseURL, (response) => {
        response.resume();
        finish(resolve);
      });

      request.on('error', (error) => {
        if (Date.now() >= deadline) {
          finish(reject, new Error(`Django E2E server did not become ready: ${error.message}`));
          return;
        }
        setTimeout(poll, 250);
      });
      request.setTimeout(1_000, () => {
        request.destroy(new Error('Readiness request timed out'));
      });
    };

    serverProcess.once('exit', handleExit);
    poll();
  });
}

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
      PASSKEY_ENABLED: '1',
      PASSKEY_RP_ID: '127.0.0.1',
      PASSKEY_RP_NAME: 'Fliegerlager E2E',
      PASSKEY_ORIGIN: baseURL,
    };

    const serverProcess = spawn('bash', ['scripts/start-e2e.sh'], { env, cwd: process.cwd() });

    await waitForHttpServer(baseURL, serverProcess);

    await use(baseURL);

    if (!serverProcess.killed) {
      serverProcess.kill();
    }
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
