import { expect, test } from '@playwright/test'

const agents = [
  {
    short_id: 'alice-codex-api',
    machine_id: 'alice-machine',
    owner: 'alice',
    kind: 'codex',
    workspace: '/workspace/service-api',
    tmux_target: 'agenttalk-e2e-api:0.0',
    receive_mode: 'auto_submit',
    status: 'online',
    updated_at: '2026-05-07T00:00:00Z',
    relay_last_seen_at: '2026-05-07T00:00:00Z',
  },
  {
    short_id: 'bob-claude-ui',
    machine_id: 'bob-machine',
    owner: 'bob',
    kind: 'claude',
    workspace: '/workspace/frontend',
    tmux_target: 'agenttalk-e2e-ui:0.0',
    receive_mode: 'paste_only',
    status: 'working',
    updated_at: '2026-05-07T00:00:00Z',
    relay_last_seen_at: '2026-05-07T00:00:00Z',
  },
]

test.beforeEach(async ({ page }) => {
  await page.route('**/api/agents', async (route) => {
    await route.fulfill({ json: { agents } })
  })
  await page.route('**/api/agents/*/context', async (route) => {
    const url = new URL(route.request().url())
    const shortId = url.pathname.split('/')[3]
    await route.fulfill({
      json: {
        short_id: shortId,
        context: `${shortId} recent output\nready for review`,
        updated_at: '2026-05-07T00:00:00Z',
      },
    })
  })
  await page.route('**/api/messages', async (route) => {
    await route.fulfill({
      json: {
        message_id: 'msg-web-1',
        sender: 'web',
        target: 'alice-codex-api',
        target_machine_id: 'alice-machine',
        body: 'Review this API',
        done_marker: '<<<AGENTTALK_DONE:msg-web-1>>>',
        status: 'sent',
        error: '',
        created_at: '2026-05-07T00:00:00Z',
        updated_at: '2026-05-07T00:00:00Z',
      },
    })
  })
  await page.route('**/api/messages/msg-web-1', async (route) => {
    await route.fulfill({
      json: {
        message_id: 'msg-web-1',
        sender: 'web',
        target: 'alice-codex-api',
        target_machine_id: 'alice-machine',
        body: 'Review this API',
        done_marker: '<<<AGENTTALK_DONE:msg-web-1>>>',
        status: 'completed',
        error: '',
        created_at: '2026-05-07T00:00:00Z',
        updated_at: '2026-05-07T00:00:00Z',
      },
    })
  })
})

test('renders agents table and side preview', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'alice-codex-api' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '/workspace/service-api' })).toBeVisible()
  await expect(page.getByRole('definition').filter({ hasText: 'alice-machine' })).toBeVisible()
  await expect(page.getByText('alice-codex-api recent output')).toBeVisible()
})

test('sends structured message from preview', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('AgentTalk Message').fill('Review this API')
  await page.getByRole('button', { name: 'Send', exact: true }).click()

  await expect(page.getByText('msg-web-1')).toBeVisible()
  await expect(page.getByText('sent')).toBeVisible()
})

test('opens detail page with terminal area', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'View Terminal' }).click()

  await expect(page.getByRole('heading', { name: 'Agent Detail' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Live Terminal' })).toBeVisible()
  await expect(page.getByTestId('live-terminal')).toBeVisible()
})

test('renders context overview', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Context' }).click()

  await expect(page.getByRole('heading', { name: 'Context Overview' })).toBeVisible()
  await expect(page.getByText('bob-claude-ui recent output')).toBeVisible()
})
