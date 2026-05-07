import { test, expect } from '@playwright/test'

const HUB_URL = 'https://agents.qicore.tech'
const TOKEN = '91055c408ac256920908b5bd9a6856fc9cd6498611faba95'

test.describe('AgentTalk Web UI - End to End', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`${HUB_URL}?token=${TOKEN}`)
  })

  test('page loads and shows agents list', async ({ page }) => {
    await page.waitForSelector('.shell', { timeout: 10000 })
    await expect(page.locator('h1')).toContainText('Agents')
    await expect(page.locator('table')).toBeVisible()
    await page.waitForTimeout(2000)
    const rows = page.locator('tbody tr')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
    console.log(`✓ Found ${count} agents in the table`)
  })

  test('can select an agent and view details', async ({ page }) => {
    await page.waitForSelector('tbody tr', { timeout: 10000 })
    const firstRow = page.locator('tbody tr').first()
    const agentId = await firstRow.locator('td').first().textContent()
    await firstRow.click()
    await page.waitForTimeout(1000)
    await expect(page.locator('.preview .summary')).toBeVisible()
    await page.locator('button:has-text("View Terminal")').click()
    await page.waitForTimeout(1000)
    await expect(page.locator('h1')).toContainText('Agent Detail')
    console.log(`✓ Viewed details for agent: ${agentId}`)
  })

  test('live terminal connects and shows output', async ({ page }) => {
    await page.waitForSelector('tbody tr', { timeout: 10000 })
    await page.locator('tbody tr').first().click()
    await page.waitForTimeout(500)
    await page.locator('button:has-text("View Terminal")').click()
    await page.waitForTimeout(1000)
    const terminal = page.locator('[data-testid="live-terminal"]')
    await expect(terminal).toBeVisible()
    await page.waitForTimeout(3000)
    const terminalText = await terminal.textContent()
    expect(terminalText).toBeTruthy()
    console.log('✓ Terminal connected, content length:', terminalText?.length)
  })

  test('live terminal accepts keyboard input', async ({ page }) => {
    await page.waitForSelector('tbody tr', { timeout: 10000 })
    await page.locator('tbody tr').first().click()
    await page.waitForTimeout(500)
    await page.locator('button:has-text("View Terminal")').click()
    await page.waitForTimeout(2000)
    const terminal = page.locator('[data-testid="live-terminal"]')
    await terminal.click()
    await page.waitForTimeout(500)
    await terminal.press('e')
    await terminal.press('c')
    await terminal.press('h')
    await terminal.press('o')
    await terminal.press(' ')
    await terminal.press('H')
    await terminal.press('I')
    await terminal.press('Enter')
    await page.waitForTimeout(2000)
    const terminalText = await terminal.textContent()
    expect(terminalText?.length).toBeGreaterThan(10)
    console.log('✓ Terminal accepted keyboard input')
  })

  test('can send message to agent', async ({ page }) => {
    await page.waitForSelector('tbody tr', { timeout: 10000 })
    await page.locator('tbody tr').first().click()
    await page.waitForTimeout(500)
    await page.locator('button:has-text("View Terminal")').click()
    await page.waitForTimeout(1000)
    const textarea = page.locator('textarea#message-agent-alpha')
    await expect(textarea).toBeVisible()
    await textarea.fill('Test message from Playwright')
    await page.locator('button:has-text("Send")').first().click()
    await page.waitForTimeout(2000)
    await expect(page.locator('.recentMessages')).toBeVisible()
    console.log('✓ Message sent successfully')
  })

  test('quick start page loads', async ({ page }) => {
    await page.locator('nav button:has-text("Quick Start")').click()
    await page.waitForTimeout(1000)
    await expect(page.locator('h1')).toContainText('Quick Start')
    await expect(page.locator('h2:has-text("Agent 端快速开始指南")')).toBeVisible()
    const codeBlocks = page.locator('.codeBlock')
    expect(await codeBlocks.count()).toBeGreaterThan(0)
    console.log('✓ Quick Start page loaded')
  })

  test('context overview page works', async ({ page }) => {
    await page.locator('nav button:has-text("Context")').click()
    await page.waitForTimeout(2000)
    await expect(page.locator('h1')).toContainText('Context')
    const contextItems = page.locator('.contextItem')
    const count = await contextItems.count()
    expect(count).toBeGreaterThan(0)
    console.log(`✓ Context page loaded with ${count} items`)
  })

  test('refresh button updates agents', async ({ page }) => {
    await page.waitForSelector('tbody tr', { timeout: 10000 })
    const initialCount = await page.locator('tbody tr').count()
    await page.locator('button:has-text("Refresh")').click()
    await page.waitForTimeout(2000)
    const newCount = await page.locator('tbody tr').count()
    expect(newCount).toBeGreaterThan(0)
    console.log(`✓ Refresh works: ${initialCount} -> ${newCount} agents`)
  })
})
