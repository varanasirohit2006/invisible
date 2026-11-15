import { defineConfig } from '@playwright/test'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

process.env.IWD_E2E_DIR ||= mkdtempSync(path.join(tmpdir(), 'iwd-e2e-'))
const testDirectory = process.env.IWD_E2E_DIR
const pythonPath =
  process.env.IWD_PYTHON ||
  (existsSync('../.venv/Scripts/python.exe') ? '../.venv/Scripts/python.exe' : 'python')
const channel =
  process.env.IWD_BROWSER_CHANNEL ||
  (process.platform === 'win32' &&
  existsSync('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    ? 'msedge'
    : undefined)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90000,
  expect: { timeout: 15000 },
  reporter: 'list',
  outputDir: path.join(testDirectory, 'results'),
  use: {
    baseURL: 'http://127.0.0.1:8765',
    viewport: { width: 1440, height: 1000 },
    channel,
    trace: 'off',
    screenshot: 'off',
  },
  webServer: {
    command: `"${pythonPath}" ../run.py --port 8765 --data-dir "${path.join(testDirectory, 'runtime')}"`,
    url: 'http://127.0.0.1:8765/api/health',
    reuseExistingServer: false,
    timeout: 60000,
    env: { OPENAI_API_KEY: '' },
  },
})
