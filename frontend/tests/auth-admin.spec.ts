import { expect, test, type Page } from '@playwright/test';

async function seedUser(page: Page, isAdmin: boolean) {
  const user = {
    user_id: isAdmin ? 'admin-user' : 'normal-user',
    username: isAdmin ? 'owner' : 'normal',
    email: isAdmin ? 'owner@example.com' : 'normal@example.com',
    is_admin: isAdmin,
  };
  await page.addInitScript(({ currentUser }) => {
    localStorage.setItem('cogentrex_token', 'test-token');
    localStorage.setItem('cogentrex_user', JSON.stringify(currentUser));
  }, { currentUser: user });
  await page.route('**/api/auth/me', route =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify(user) }),
  );
  await page.route('**/api/learning-media/catalog', route =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) }),
  );
}

test('registration requires email before submission', async ({ page }) => {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'Register' }).click();
  await page.getByLabel('Username').fill('new-user');
  await page.getByLabel('Password').fill('secret1');

  await expect(page.getByLabel('Email')).toHaveAttribute('required', '');
  await expect(page.getByRole('button', { name: 'Create Account' })).toBeDisabled();

  await page.getByLabel('Email').fill('new-user@example.com');
  await expect(page.getByRole('button', { name: 'Create Account' })).toBeEnabled();
});

test('dashboard navigation is visible only to administrators', async ({ page }) => {
  await seedUser(page, false);
  await page.goto('/learn');
  await expect(page.getByRole('link', { name: 'Dashboard' })).toHaveCount(0);

  await page.evaluate(() => {
    const user = JSON.parse(localStorage.getItem('cogentrex_user') || '{}');
    user.is_admin = true;
    localStorage.setItem('cogentrex_user', JSON.stringify(user));
  });
  await page.unroute('**/api/auth/me');
  await page.route('**/api/auth/me', route =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: 'admin-user',
        username: 'owner',
        email: 'owner@example.com',
        is_admin: true,
      }),
    }),
  );
  await page.reload();
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible();
});
