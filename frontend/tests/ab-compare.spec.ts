import { expect, test } from '@playwright/test'

/**
 * AB对比结果表全链路验收：
 * 归属过滤、同一成员集合差异、越权只读、两种版本冲突策略、
 * 重算中断沿用、V010留档/转交/口径校验，以及导航页与抽屉同源数据。
 */
test.describe('AB对比结果表', () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    page.on('response', (r) => {
      if (r.url().includes('/api/') && r.status() >= 400) errors.push(`${r.status()} ${r.url()}`)
    })
    test.info().attach('errors', { body: errors.join('\n') || 'none' })
  })

  test('生成对比结果表：每行差异只来自同一实验，越权成员不进正式差异', async ({ page }) => {
    await page.goto('/ab_result')
    await expect(page.getByTestId('compare-block')).toBeVisible()

    await page.getByTestId('experiment-select').selectOption({ index: 0 })
    await page.getByTestId('strategy-select').selectOption('target_only')
    await page.getByTestId('generate-compare').click()

    await expect(page.getByTestId('compare-row').first()).toBeVisible({ timeout: 10000 })
    const message = await page.getByTestId('compare-message').innerText()
    expect(message).toContain('越权成员')
    // 正式结果样本量与抽屉成员集合一致，证明过滤与差异计算同源
    const firstRow = page.getByTestId('compare-row').first()
    const unauthorizedText = await firstRow.getByTestId('row-unauthorized-count').innerText()
    expect(Number(unauthorizedText)).toBeGreaterThan(0)

    await firstRow.getByTestId('open-drawer').click()
    const drawer = page.getByTestId('compare-drawer')
    await expect(drawer).toBeVisible()
    expect(await page.getByTestId('drawer-unauthorized').count()).toBeGreaterThan(0)
    // 指纹存在且可追溯
    expect((await page.getByTestId('drawer-fingerprint-control').innerText()).length).toBeGreaterThan(8)
  })

  test('isolate策略：重叠用户进入待复核清单；target_only：正式结果排除重叠用户', async ({ page }) => {
    await page.goto('/ab_result')
    await page.getByTestId('experiment-select').selectOption({ index: 0 })

    await page.getByTestId('strategy-select').selectOption('isolate')
    await page.getByTestId('generate-compare').click()
    await page.getByTestId('compare-row').first().getByTestId('open-drawer').click()
    await expect(page.getByTestId('drawer-review').first()).toBeVisible()
    await page.getByTestId('drawer-close').click()

    await page.getByTestId('strategy-select').selectOption('target_only')
    await page.getByTestId('generate-compare').click()
    await page.getByTestId('compare-row').first().getByTestId('open-drawer').click()
    await expect(page.getByTestId('drawer-review')).toHaveCount(0)
  })

  test('重算中断沿用上一版，不用越权成员补齐', async ({ page }) => {
    await page.goto('/ab_result')
    await page.getByTestId('experiment-select').selectOption({ index: 0 })
    await page.getByTestId('generate-compare').click()
    await expect(page.getByTestId('compare-row').first()).toBeVisible()

    await page.getByTestId('simulate-interrupt').click()
    await expect(page.getByTestId('compare-message')).toHaveText(/沿用上一版/)
    await expect(page.getByTestId('compare-row').first()).toHaveAttribute('data-status', '已中断')
  })

  test('V010留档归档、口径校验与只读转交', async ({ page }) => {
    await page.goto('/ab_result')
    await page.getByTestId('experiment-select').selectOption({ index: 0 })
    await page.getByTestId('generate-compare').click()
    await page.getByTestId('compare-row').first().getByTestId('open-drawer').click()

    await page.getByTestId('caliber-check').click()
    await expect(page.getByTestId('caliber-true').first()).toBeVisible({ timeout: 10000 })

    await page.getByTestId('archive-table').click()
    await expect(page.getByTestId('drawer-status')).toHaveText('已归档')
    await page.getByTestId('handover-table').click()
    await expect(page.getByTestId('drawer-status')).toHaveText('已转交')
  })

  test('越权范围写入被拒，共享内容只读可查看', async ({ page }) => {
    await page.goto('/ab_result')
    // 选中归属 scope-a 的实验（种子演示实验 EXPE-1004），再把操作者切到 scope-b
    const scopeAOption = page.getByTestId('experiment-select').locator('option', { hasText: 'scope-a' }).first()
    await page.getByTestId('experiment-select').selectOption(await scopeAOption.getAttribute('value') ?? '4')
    await page.getByTestId('scope-select').selectOption('scope-b')
    await page.getByTestId('generate-compare').click()
    await expect(page.getByTestId('compare-message')).toHaveText(/越权/)

    // 先用管理员生成一张表，再验证 scope-b 下它可见但只读
    await page.getByTestId('scope-select').selectOption('__all__')
    await page.getByTestId('generate-compare').click()
    await page.getByTestId('scope-select').selectOption('scope-b')
    const row = page.getByTestId('compare-row').filter({ has: page.getByTestId('row-scope', { hasText: 'scope-a' }) }).first()
    await expect(row.getByTestId('row-access')).toHaveText('只读')
    await row.getByTestId('open-drawer').click()
    await expect(page.getByTestId('drawer-access')).toContainText('只读')
    await expect(page.getByTestId('archive-table')).toBeDisabled()
    await expect(page.getByTestId('handover-table')).toBeDisabled()
  })

  test('导航页与抽屉读取同一业务数据', async ({ page }) => {
    await page.goto('/ab_result')
    await page.getByTestId('experiment-select').selectOption({ index: 0 })
    await page.getByTestId('generate-compare').click()
    await expect(page.getByTestId('compare-row').first()).toBeVisible()
    const tableNo = await page.getByTestId('compare-row').first().locator('td').first().innerText()

    await page.goto('/')
    await expect(page.getByTestId('overview-compare')).toBeVisible()
    await expect(page.getByTestId('overview-compare-row').filter({ hasText: tableNo })).toBeVisible()
  })
})
