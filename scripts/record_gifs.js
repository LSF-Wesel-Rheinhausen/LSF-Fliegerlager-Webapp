const { chromium } = require('@playwright/test');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });

  // Add custom mouse pointer visualization
  await context.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const cursor = document.createElement('div');
      cursor.style.width = '40px';
      cursor.style.height = '40px';
      cursor.style.backgroundColor = 'rgba(255, 152, 0, 0.6)';
      cursor.style.border = '2px solid white';
      cursor.style.borderRadius = '50%';
      cursor.style.position = 'fixed';
      cursor.style.pointerEvents = 'none';
      cursor.style.zIndex = '999999';
      cursor.style.transition = 'width 0.1s, height 0.1s, background-color 0.1s, transform 0.1s';
      cursor.style.transform = 'translate(-50%, -50%)';
      cursor.style.display = 'block'; // Always visible
      cursor.style.top = '50%';
      cursor.style.left = '50%';
      document.body.appendChild(cursor);

      document.addEventListener('mousemove', e => {
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
      });

      document.addEventListener('mousedown', () => {
        cursor.style.backgroundColor = 'rgba(255, 152, 0, 0.9)';
        cursor.style.width = '30px';
        cursor.style.height = '30px';
      });

      document.addEventListener('mouseup', () => {
        cursor.style.backgroundColor = 'rgba(255, 152, 0, 0.6)';
        cursor.style.width = '40px';
        cursor.style.height = '40px';
      });
    });
  });

  const page = await context.newPage();

  async function smoothMove(locator) {
      const box = await locator.boundingBox();
      if (box) {
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 10 });
      }
      await locator.hover();
      await page.waitForTimeout(300);
  }

  async function recordAction(name, actionFn) {
    console.log(`Recording ${name}...`);
    fs.mkdirSync(`frames/${name}`, { recursive: true });
    let frame = 0;
    let recording = true;

    // 10 fps
    const interval = setInterval(async () => {
      if (!recording) return;
      try {
        await page.screenshot({ path: `frames/${name}/frame_${String(frame++).padStart(3, '0')}.png` });
      } catch (e) {}
    }, 100);

    await new Promise(r => setTimeout(r, 1000));
    await actionFn();
    await new Promise(r => setTimeout(r, 2000));
    
    recording = false;
    clearInterval(interval);
  }

  await page.goto('http://localhost:8000/');
  
  // 1. kiosk_login
  await recordAction('kiosk_login', async () => {
    await page.waitForTimeout(500);
    const select = page.locator('select[name="participant"]');
    await smoothMove(select);
    await select.selectOption({ label: 'Lara Neu' });
    await page.waitForTimeout(500);

    const pinInput = page.locator('input[name="pin"]');
    await smoothMove(pinInput);
    await pinInput.click();
    await pinInput.type('4321', { delay: 200 });
    await page.waitForTimeout(500);

    const submitBtn = page.locator('button[type="submit"]:has-text("Anmelden")');
    await smoothMove(submitBtn);
    await submitBtn.click();
    
    // Redirects to PIN setup
    await page.waitForSelector('text=PIN festlegen', { timeout: 10000 });
    await page.waitForTimeout(500);

    const newPin = page.locator('input[name="pin"]');
    await smoothMove(newPin);
    await newPin.click();
    await newPin.type('4321', { delay: 150 });
    await page.waitForTimeout(200);

    const repeatPin = page.locator('input[name="pin_repeat"]');
    await smoothMove(repeatPin);
    await repeatPin.click();
    await repeatPin.type('4321', { delay: 150 });
    await page.waitForTimeout(500);

    const savePinBtn = page.locator('button[type="submit"]');
    await smoothMove(savePinBtn);
    await savePinBtn.click();

    await page.waitForSelector('text=Getränk buchen', { timeout: 10000 });
  });

  // 2. kiosk_drinks
  await recordAction('kiosk_drinks', async () => {
    await page.waitForTimeout(500);
    const drinkBtn = page.locator('button.drink-card').first();
    if (await drinkBtn.isVisible()) {
      await smoothMove(drinkBtn);
      await drinkBtn.click();
      await page.waitForTimeout(1000); 
      
      const qtyBtn = page.locator('button[data-drink-quantity="1"]');
      await smoothMove(qtyBtn);
      await qtyBtn.click();
      
      await page.waitForSelector('.success, .error, h1', { timeout: 10000 });
      await page.waitForTimeout(500);
      await page.mouse.wheel(0, 500);
      await page.waitForTimeout(1500);
    }
  });

  // 3. kiosk_meals
  await recordAction('kiosk_meals', async () => {
    await page.waitForTimeout(500);
    const mealDay = page.locator('.meal-calendar-day:not(.is-past)').first();
    if (await mealDay.isVisible()) {
        await smoothMove(mealDay);
        await mealDay.click();
        await page.waitForTimeout(1000);
        
        const checkbox = page.locator('#meal-dialog input[type="checkbox"]').first();
        await smoothMove(checkbox);
        await checkbox.click();
        await page.waitForTimeout(500);
        
        const saveBtn = page.locator('#meal-dialog button[type="submit"]');
        await smoothMove(saveBtn);
        await saveBtn.click();
        
        await page.waitForSelector('.success, .error, h1', { timeout: 10000 });
        await page.waitForTimeout(500);
        await page.mouse.wheel(0, 600);
        await page.waitForTimeout(1500);
    }
  });

  // 4. kiosk_family
  await recordAction('kiosk_family', async () => {
    await page.waitForTimeout(500);
    await page.mouse.wheel(0, -600); // Scroll back up to see the button
    await page.waitForTimeout(500);

    const addBtn = page.locator('button[data-open-family-dialog]');
    if (await addBtn.isVisible()) {
        await smoothMove(addBtn);
        await addBtn.click();
        await page.waitForTimeout(1000);
        
        const fName = page.locator('#family-dialog input[name="family-first_name"]');
        await smoothMove(fName);
        await fName.click();
        await fName.type('Mini', { delay: 150 });
        await page.waitForTimeout(200);

        const lName = page.locator('#family-dialog input[name="family-last_name"]');
        await smoothMove(lName);
        await lName.click();
        await lName.type('Neu', { delay: 150 });
        await page.waitForTimeout(500);

        const roleSel = page.locator('#family-dialog select[name="family-role"]');
        await smoothMove(roleSel);
        await roleSel.selectOption({ value: 'child' });
        await page.waitForTimeout(500);
        
        const saveBtn = page.locator('#family-dialog button[type="submit"]');
        await smoothMove(saveBtn);
        await saveBtn.click();
        
        await page.waitForSelector('.success, .error, h1', { timeout: 10000 });
    }
  });

  // 5. kiosk_shifts
  await recordAction('kiosk_shifts', async () => {
    const shiftsLink = page.locator('a[href="/kiosk/shifts/"]');
    if (await shiftsLink.isVisible()) {
        await smoothMove(shiftsLink);
        await shiftsLink.click();
        await page.waitForSelector('h1', { timeout: 10000 });
        await page.waitForTimeout(1000);
        
        const shiftBtn = page.locator('button:has-text("Übernehmen")').first();
        if (await shiftBtn.isVisible()) {
            await smoothMove(shiftBtn);
            await shiftBtn.click();
            
            await page.waitForTimeout(1000);
            const confirmBtn = page.locator('button[name="action"][value="claim_shift"]');
            await smoothMove(confirmBtn);
            await confirmBtn.click();
            await page.waitForSelector('.success, .error, h1', { timeout: 10000 });
        } else {
            await page.mouse.wheel(0, 300);
        }
    } else {
        await page.goto('http://localhost:8000/kiosk/shifts/');
        await page.waitForTimeout(1000);
        await page.mouse.wheel(0, 300);
    }
  });

  await browser.close();
})();
