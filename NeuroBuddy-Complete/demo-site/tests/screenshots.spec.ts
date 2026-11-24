import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const outDir = '/cursor/stores/bc-a4d5277f-af64-4e89-bafa-14ad6357afc6/media/demo-site'

const shots = [
  { name: 'desktop-1440-hero', width: 1440, height: 900, hash: '#hero' },
  { name: 'desktop-1440-pipeline', width: 1440, height: 900, hash: '#pipeline' },
  { name: 'desktop-1440-library', width: 1440, height: 900, hash: '#library' },
  { name: 'desktop-1440-tasks', width: 1440, height: 900, hash: '#tasks' },
  { name: 'desktop-1440-reports', width: 1440, height: 900, hash: '#reports' },
  { name: 'desktop-1440-packages', width: 1440, height: 900, hash: '#advanced' },
  { name: 'desktop-1440-close', width: 1440, height: 900, hash: '#close' },
  { name: 'desktop-1280-hero', width: 1280, height: 800, hash: '#hero' },
  { name: 'tablet-1024-library', width: 1024, height: 768, hash: '#library' },
  { name: 'tablet-768-hero', width: 768, height: 1024, hash: '#hero' },
  { name: 'mobile-390-hero', width: 390, height: 844, hash: '#hero' },
  { name: 'mobile-390-library', width: 390, height: 844, hash: '#library' },
  { name: 'mobile-390-tasks', width: 390, height: 844, hash: '#tasks' },
  { name: 'mobile-320-hero', width: 320, height: 568, hash: '#hero' },
  { name: 'mobile-320-close', width: 320, height: 568, hash: '#close' },
]

test('capture real viewport screenshots', async ({ page }) => {
  fs.mkdirSync(outDir, { recursive: true })
  for (const shot of shots) {
    await page.setViewportSize({ width: shot.width, height: shot.height })
    await page.goto('/')
    const target = page.locator(shot.hash)
    await expect(target).toBeVisible()
    await page.evaluate((hash) => {
      document.documentElement.style.scrollBehavior = 'auto'
      const el = document.querySelector(hash)
      if (!(el instanceof HTMLElement)) return
      const top = el.getBoundingClientRect().top + window.scrollY - 128
      window.scrollTo({ top: Math.max(0, top), behavior: 'instant' })
    }, shot.hash)
    if (shot.hash === '#hero') {
      const heroImg = page.locator('#hero img[src="/media/eeg-subject.jpg"]')
      await expect(heroImg).toBeVisible()
      await expect
        .poll(async () => heroImg.evaluate((el) => (el as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0)
    }
    if (shot.hash === '#pipeline') {
      const pin = page.locator('#pipeline img[src="/media/pipeline-eeg-woman.jpg"]')
      await expect(pin).toBeVisible()
      await expect
        .poll(async () => pin.evaluate((el) => (el as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0)
      await expect(page.locator('#pipeline img[src="/media/api-wordmark.png"]')).toBeVisible()
    }
    if (shot.hash === '#tasks') {
      const taskImg = page.locator('#tasks img').first()
      await expect(taskImg).toBeVisible()
      await expect
        .poll(async () => taskImg.evaluate((el) => (el as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0)
    }
    if (shot.hash === '#library') {
      await expect(page.locator('#library video')).toBeVisible()
    }
    if (shot.hash === '#close') {
      await expect(page.locator('#close img[src="/media/api-wordmark.png"]')).toBeVisible()
      await expect(page.getByRole('listbox', { name: 'Coaching struggles' })).toBeVisible()
    }
    if (shot.hash === '#advanced') {
      const analysis = page.locator('#advanced img[src="/media/Screenshot_Analysis.png"]')
      await expect(analysis).toBeVisible()
      await expect
        .poll(async () => analysis.evaluate((el) => (el as HTMLImageElement).naturalWidth))
        .toBeGreaterThan(0)
    }
    await page.waitForTimeout(200)
    const file = path.join(outDir, `${shot.name}.png`)
    await page.screenshot({ path: file, fullPage: false })
    expect(fs.existsSync(file)).toBeTruthy()
  }

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  const reduced = path.join(outDir, 'desktop-1440-reduced-motion.png')
  await page.screenshot({ path: reduced, fullPage: false })
  expect(fs.existsSync(reduced)).toBeTruthy()
})
