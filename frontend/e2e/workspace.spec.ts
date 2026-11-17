import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const directory = process.env.IWD_E2E_DIR!

async function pair(page: Page) {
  await page.goto('/')
  await expect(page).toHaveTitle('Invisible — Work Detector')
  await expect(page.getByRole('heading', { name: 'Connect your workspace' })).toBeVisible()
  await page
    .getByLabel('Local pairing token')
    .fill(readFileSync(path.join(directory, 'runtime', 'token'), 'utf8').trim())
  await page.getByRole('button', { name: 'Open workspace' }).click()
  await expect(page.getByRole('heading', { name: 'A clearer picture of your work.' })).toBeVisible()
}

function monitorErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return errors
}

async function navigate(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link', { name, exact: true })
    .click()
}

async function observed(page: Page, eventType: string, filename: string) {
  await expect
    .poll(async () => {
      const response = await page.request.get(
        `/api/events?q=${encodeURIComponent(filename)}&limit=100`,
      )
      const data = await response.json()
      return data.items.some((event: { event_type: string }) => event.event_type === eventType)
    })
    .toBe(true)
}

test('pairing, sample exploration, filtering, dialogs, and mobile layout', async ({ page }) => {
  const errors = monitorErrors(page)
  await pair(page)
  await page.getByRole('button', { name: 'Explore sample activity' }).click()
  await expect(page.getByText('Sample data', { exact: true })).toBeVisible()
  await expect(page.locator('.workflow-row')).toHaveCount(3)
  await page.screenshot({ path: path.join(directory, 'overview-desktop.png'), fullPage: false })
  await page
    .locator('.workflow-row')
    .filter({ hasText: 'Process invoices' })
    .getByRole('button', { name: 'Review', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('A preview of what’s possible.')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Run automation' })).toHaveCount(0)
  await page.keyboard.press('Tab')
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await navigate(page, 'Activity')
  await page.getByRole('textbox', { name: 'Search activity' }).fill('Invoice_001')
  await page.getByRole('combobox', { name: 'Filter activity type' }).selectOption('file_moved')
  await expect(page.locator('.activity-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.activity-table tbody')).toContainText('Moved')
  await page.getByText('Show observed paths').click()
  await expect(page.locator('.observed-paths')).toContainText('Invoice_001.pdf')
  await page.getByRole('button', { name: 'My activity', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Nothing observed yet' })).toBeVisible()
  await navigate(page, 'Overview')
  await page.getByRole('button', { name: 'Sample activity', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.workflow-row')).toHaveCount(3)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  for (const link of await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link')
    .all()) {
    const box = await link.boundingBox()
    expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy()
  }
  await page.screenshot({ path: path.join(directory, 'overview-mobile.png'), fullPage: true })
  await navigate(page, 'Settings')
  await expect(page.getByRole('button', { name: 'Save settings' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.getByRole('button', { name: 'Disconnect dashboard' }).click()
  await expect(page.getByRole('heading', { name: 'Connect your workspace' })).toBeVisible()
  await pair(page)
  expect(errors).toEqual([])
  console.log(`QA screenshots: ${directory}`)
})

test('real watcher to discovery, preview, approval, execution, and pause', async ({ page }) => {
  const errors = monitorErrors(page)
  await pair(page)
  const work = path.join(directory, 'work')
  const archive = path.join(work, 'archive')
  mkdirSync(archive, { recursive: true })
  await navigate(page, 'Settings')
  await page.getByRole('textbox', { name: 'Folder path' }).fill(work)
  await page.getByRole('button', { name: 'Add folder' }).click()
  await page.getByRole('checkbox', { name: /I approve file activity monitoring/ }).check()
  await page.getByRole('switch', { name: 'Activity monitoring' }).click()
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Settings saved', { exact: true })).toBeVisible()
  await expect
    .poll(async () => (await (await page.request.get('/api/status')).json()).watching)
    .toBe(1)
  for (let cycle = 0; cycle < 3; cycle += 1) {
    const original = path.join(work, `cycle-${cycle}.txt`)
    const renamed = path.join(work, `cycle-${cycle}-reviewed.txt`)
    const destination = path.join(archive, `cycle-${cycle}-reviewed.txt`)
    writeFileSync(original, `Synthetic QA cycle ${cycle}`)
    await observed(page, 'file_created', `cycle-${cycle}`)
    renameSync(original, renamed)
    await observed(page, 'file_renamed', `cycle-${cycle}`)
    renameSync(renamed, destination)
    await observed(page, 'file_moved', `cycle-${cycle}`)
  }
  await navigate(page, 'Workflows')
  await page.getByRole('button', { name: 'Discover patterns' }).click()
  await expect(page.locator('.workflow-row').filter({ hasText: 'Create TXT' })).toHaveCount(1)
  const source = path.join(work, 'next-file.txt')
  const target = path.join(work, 'organized', 'done.txt')
  writeFileSync(source, 'This exact content must survive the approved run.')
  await observed(page, 'file_created', 'next-file')
  await page
    .locator('.workflow-row')
    .filter({ hasText: 'Create TXT' })
    .getByRole('button', { name: 'Review', exact: true })
    .click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Source file', { exact: true }).fill(source)
  await dialog.getByLabel('New filename or template').fill('done.txt')
  await dialog.getByRole('button', { name: 'Edit destination', exact: true }).click()
  await dialog.getByLabel('Destination folder', { exact: true }).fill(path.dirname(target))
  await dialog.getByRole('button', { name: 'Use this folder', exact: true }).click()
  await dialog.getByRole('button', { name: 'Preview changes' }).click()
  await expect(dialog.getByText('Exact changes to review')).toBeVisible()
  expect(existsSync(source)).toBe(true)
  expect(existsSync(target)).toBe(false)
  await page.screenshot({ path: path.join(directory, 'automation-preview.png'), fullPage: false })
  await dialog.getByRole('button', { name: 'Approve this plan' }).click()
  await expect(dialog.getByText('Approved for one run.', { exact: false })).toBeVisible()
  expect(existsSync(source)).toBe(true)
  expect(existsSync(target)).toBe(false)
  await dialog.getByRole('button', { name: 'Run automation' }).click()
  await expect(dialog.getByRole('heading', { name: 'Your automation is queued.' })).toBeVisible()
  await dialog.getByRole('button', { name: 'View run history' }).click()
  await expect(page.locator('.status-badge').filter({ hasText: 'Completed' })).toHaveCount(1)
  expect(existsSync(source)).toBe(false)
  expect(readFileSync(target, 'utf8')).toBe('This exact content must survive the approved run.')
  await page.locator('.run-row summary').click()
  await expect(page.locator('.step-result').filter({ hasText: 'Completed' })).toHaveCount(2)
  await page.screenshot({ path: path.join(directory, 'completed-run.png'), fullPage: false })
  await navigate(page, 'Settings')
  await page.getByRole('switch', { name: 'Activity monitoring' }).click()
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Settings saved', { exact: true })).toBeVisible()
  await expect
    .poll(async () => (await (await page.request.get('/api/status')).json()).watching)
    .toBe(0)
  writeFileSync(path.join(work, 'paused-check.txt'), 'Must not be observed')
  await page.waitForTimeout(1500)
  const pausedEvents = await (await page.request.get('/api/events?q=paused-check')).json()
  expect(pausedEvents.total).toBe(0)
  await page.getByRole('button', { name: 'Clear activity', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Clear real activity' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect((await (await page.request.get('/api/events')).json()).total).toBe(0)
  expect((await (await page.request.get('/api/runs')).json()).items[0].status).toBe('succeeded')
  expect(errors).toEqual([])
})

test('enabled monitoring waits for folders without being labeled paused', async ({ page }) => {
  const errors = monitorErrors(page)
  let watching = 0
  let enabled = true
  await page.route('**/api/dashboard?*', async (route) => {
    const response = await route.fetch()
    const dashboard = await response.json()
    await route.fulfill({
      response,
      json: {
        ...dashboard,
        settings: { ...dashboard.settings, monitoring_enabled: enabled },
        agent: { ...dashboard.agent, connected: true, watching, error: null },
      },
    })
  })
  await pair(page)
  await expect(page.locator('.agent-indicator')).toHaveText(
    'Monitoring enabled · waiting for folders',
  )
  await expect(page.locator('.monitor-main h3')).toHaveText(
    'Monitoring enabled. Waiting for folders.',
  )
  await page.screenshot({ path: path.join(directory, 'monitoring-waiting.png'), fullPage: true })
  watching = 2
  await expect(page.locator('.agent-indicator')).toHaveText('Observing 2 folders')
  await expect(page.locator('.monitor-main h3')).toHaveText('Observing approved folders')
  enabled = false
  await page.reload()
  await expect(page.locator('.agent-indicator')).toHaveText('Monitoring paused')
  await expect(page.locator('.monitor-main h3')).toHaveText('Connected. Monitoring paused.')
  expect(errors).toEqual([])
})

test('learned image destinations keep cars and buses separate and ask about unclear names', async ({
  page,
}) => {
  const errors = monitorErrors(page)
  await pair(page)
  const root = path.join(directory, 'image-work')
  const downloads = path.join(root, 'downloads')
  const cars = path.join(root, 'photos', 'car')
  const buses = path.join(root, 'photos', 'bus')
  for (const folder of [downloads, cars, buses]) mkdirSync(folder, { recursive: true })
  await navigate(page, 'Settings')
  await page.getByRole('textbox', { name: 'Folder path' }).fill(root)
  await page.getByRole('button', { name: 'Add folder', exact: true }).click()
  await page.getByRole('checkbox', { name: /I approve file activity monitoring/ }).check()
  await page.getByLabel('Minimum repeated sessions').selectOption('2')
  const monitoring = page.getByRole('switch', { name: 'Activity monitoring' })
  if ((await monitoring.getAttribute('aria-checked')) === 'false') await monitoring.click()
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Settings saved', { exact: true })).toBeVisible()
  await expect
    .poll(async () => (await (await page.request.get('/api/status')).json()).watching)
    .toBe(2)
  for (const [category, folder] of [
    ['car', cars],
    ['bus', buses],
  ]) {
    const source = path.join(downloads, `${category}-lesson.jpg`)
    writeFileSync(source, `Synthetic ${category} image fixture`)
    await observed(page, 'file_created', `${category}-lesson`)
    renameSync(source, path.join(folder, path.basename(source)))
    await observed(page, 'file_moved', `${category}-lesson`)
  }
  await navigate(page, 'Workflows')
  await page.getByRole('button', { name: 'Discover patterns' }).click()
  const workflow = page.locator('.workflow-row').filter({ hasText: 'Create JPG' })
  await expect(workflow).toHaveCount(1)
  const car = path.join(downloads, 'car-next.jpg')
  const bus = path.join(downloads, 'bus-next.jpg')
  writeFileSync(car, 'Car contents must be preserved')
  writeFileSync(bus, 'Bus contents must be preserved')
  await observed(page, 'file_created', 'bus-next')

  for (const [source, folder] of [
    [car, cars],
    [bus, buses],
  ]) {
    await navigate(page, 'Workflows')
    await workflow.getByRole('button', { name: 'Review', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Source file', { exact: true }).fill(source)
    await expect(dialog.locator('.destination-path')).toHaveText(folder)
    await expect(
      dialog.getByRole('button', { name: 'Preview changes', exact: true }),
    ).toBeDisabled()
    await dialog.getByRole('button', { name: 'Use this folder', exact: true }).click()
    if (source === car) {
      // Changing the source must invalidate the previous confirmation.
      await dialog.getByLabel('Source file', { exact: true }).fill(bus)
      await expect(
        dialog.getByRole('button', { name: 'Preview changes', exact: true }),
      ).toBeDisabled()
      await expect(dialog.locator('.destination-path')).toHaveText(buses)
      await dialog.getByLabel('Source file', { exact: true }).fill(car)
      await expect(dialog.locator('.destination-path')).toHaveText(cars)
      await dialog.getByRole('button', { name: 'Use this folder', exact: true }).click()
    }
    await page.screenshot({
      path: path.join(directory, `destination-${path.basename(folder)}.png`),
      fullPage: false,
    })
    await dialog.getByRole('button', { name: 'Preview changes', exact: true }).click()
    await expect(dialog.getByText('Exact changes to review')).toBeVisible()
    expect(existsSync(source)).toBe(true)
    const target = path.join(folder, path.basename(source))
    expect(existsSync(target)).toBe(false)
    await dialog.getByRole('button', { name: 'Approve this plan', exact: true }).click()
    expect(existsSync(source)).toBe(true)
    await dialog.getByRole('button', { name: 'Run automation', exact: true }).click()
    await dialog.getByRole('button', { name: 'View run history', exact: true }).click()
    await expect.poll(() => existsSync(target)).toBe(true)
    expect(existsSync(source)).toBe(false)
    expect(readFileSync(target, 'utf8')).toBe(
      source === car ? 'Car contents must be preserved' : 'Bus contents must be preserved',
    )
  }

  const unknown = path.join(downloads, 'IMG_1234.jpg')
  writeFileSync(unknown, 'Unclear file stays put until a destination is approved')
  await observed(page, 'file_created', 'IMG_1234')
  await navigate(page, 'Workflows')
  await workflow.getByRole('button', { name: 'Review', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Source file', { exact: true }).fill(unknown)
  await expect(dialog.getByRole('button', { name: 'Use car', exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Use bus', exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Preview changes', exact: true })).toBeDisabled()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({
    path: path.join(directory, 'destination-uncertain-mobile.png'),
    fullPage: true,
  })
  await dialog.getByRole('button', { name: 'Edit destination', exact: true }).click()
  const edited = path.join(root, 'photos', 'reviewed')
  await dialog.getByLabel('Destination folder', { exact: true }).fill(edited)
  await dialog.getByRole('button', { name: 'Use this folder', exact: true }).click()
  await dialog.getByRole('button', { name: 'Preview changes', exact: true }).click()
  await expect(dialog.getByText('Exact changes to review')).toBeVisible()
  await expect(dialog.locator('.preview-actions')).toContainText(edited)
  expect(existsSync(unknown)).toBe(true)
  expect(existsSync(path.join(edited, path.basename(unknown)))).toBe(false)
  expect(errors).toEqual([])
})

test('master button files every recognized pending file in one approved batch', async ({
  page,
}) => {
  const errors = monitorErrors(page)
  await pair(page)
  const root = path.join(directory, 'batch-work')
  const downloads = path.join(root, 'downloads')
  const trucks = path.join(root, 'photos', 'truck')
  const vans = path.join(root, 'photos', 'van')
  const reviewed = path.join(root, 'photos', 'reviewed')
  for (const folder of [downloads, trucks, vans]) mkdirSync(folder, { recursive: true })
  await navigate(page, 'Settings')
  await page.getByRole('textbox', { name: 'Folder path' }).fill(root)
  await page.getByRole('button', { name: 'Add folder', exact: true }).click()
  await page.getByRole('checkbox', { name: /I approve file activity monitoring/ }).check()
  await page.getByLabel('Minimum repeated sessions').selectOption('2')
  const monitoring = page.getByRole('switch', { name: 'Activity monitoring' })
  if ((await monitoring.getAttribute('aria-checked')) === 'false') await monitoring.click()
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText('Settings saved', { exact: true })).toBeVisible()
  await expect
    .poll(async () => (await (await page.request.get('/api/status')).json()).watching)
    .toBe(3)
  for (const [category, folder] of [
    ['truck', trucks],
    ['van', vans],
  ]) {
    const source = path.join(downloads, `${category}-lesson.jpg`)
    writeFileSync(source, `Synthetic ${category} image fixture`)
    await observed(page, 'file_created', `${category}-lesson`)
    renameSync(source, path.join(folder, path.basename(source)))
    await observed(page, 'file_moved', `${category}-lesson`)
  }
  await navigate(page, 'Workflows')
  await page.getByRole('button', { name: 'Discover patterns' }).click()
  await expect(page.locator('.workflow-row').filter({ hasText: 'Create JPG' })).toHaveCount(1)
  const pending = [
    { name: 'truck-next.jpg', folder: trucks, content: 'Batch truck contents' },
    { name: 'van-next.jpg', folder: vans, content: 'Batch van contents' },
    { name: 'SCAN_7777.jpg', folder: reviewed, content: 'Batch unclear contents' },
  ]
  for (const file of pending) {
    writeFileSync(path.join(downloads, file.name), file.content)
    await observed(page, 'file_created', file.name.replace('.jpg', ''))
  }
  await page.getByRole('button', { name: 'File everything' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'File everything at once' })).toBeVisible()
  await expect(dialog.locator('.batch-summary')).toBeVisible()
  const mine = new Set(pending.map((file) => file.name))
  // Earlier tests may leave other pending files; keep only this batch's three.
  for (const row of await dialog.locator('.batch-row').all()) {
    const name = (await row.locator('.batch-name strong').innerText()).trim()
    if (!mine.has(name)) {
      const box = row.getByRole('checkbox')
      if (await box.isChecked()) await box.uncheck()
    }
  }
  const truckRow = dialog.locator('.batch-row').filter({ hasText: 'truck-next.jpg' })
  await expect(truckRow.getByLabel('Destination folder', { exact: true })).toHaveValue(trucks)
  const vanRow = dialog.locator('.batch-row').filter({ hasText: 'van-next.jpg' })
  await expect(vanRow.getByLabel('Destination folder', { exact: true })).toHaveValue(vans)
  const unclearRow = dialog.locator('.batch-row').filter({ hasText: 'SCAN_7777.jpg' })
  await expect(unclearRow.locator('.status-badge')).toHaveText('Needs a folder')
  const runAll = dialog.getByRole('button', { name: /Approve & run all/ })
  await expect(runAll).toBeDisabled()
  await page.screenshot({ path: path.join(directory, 'batch-review.png'), fullPage: false })
  await unclearRow.getByLabel('Destination folder', { exact: true }).fill(reviewed)
  await expect(runAll).toBeEnabled()
  await runAll.click()
  await expect(dialog.getByRole('heading', { name: 'Your batch is queued.' })).toBeVisible()
  await expect(dialog.getByText('3 approved files', { exact: false })).toBeVisible()
  await dialog.getByRole('button', { name: 'View run history' }).click()
  for (const file of pending) {
    const target = path.join(file.folder, file.name)
    await expect.poll(() => existsSync(target)).toBe(true)
    expect(existsSync(path.join(downloads, file.name))).toBe(false)
    expect(readFileSync(target, 'utf8')).toBe(file.content)
  }
  const runs = await (await page.request.get('/api/runs?limit=3')).json()
  expect(runs.items).toHaveLength(3)
  expect(runs.items.every((run: { status: string }) => run.status === 'succeeded')).toBe(true)
  await page.screenshot({ path: path.join(directory, 'batch-completed.png'), fullPage: false })
  expect(errors).toEqual([])
})
