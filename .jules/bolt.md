## 2026-01-18 - Playwright Browser Reuse in Polling Loops
**Learning:** In scraping scripts that poll a URL, launching a new Playwright browser instance for every iteration is a massive performance bottleneck. The overhead of `browser.launch()` can be seconds, dominating the polling interval.
**Action:** When optimizing scrapers, refactor the main loop to be asynchronous and initialize the browser once outside the loop. Pass the browser instance to the fetching function.
