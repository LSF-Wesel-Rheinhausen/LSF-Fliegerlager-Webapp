# Kiosk Layout Improvements & Billing Polish

- Implemented an `abs_value` template filter to display negative balances correctly with a clean minus sign instead of duplicating the sign or formatting weirdly.
- Reduced the summary text in the Kiosk home screen by hiding gross ("Brutto") and due ("Soll") values, making it cleaner.
- Made the Kiosk summary dialog fully responsive, limiting its maximum width and adapting to small viewports.
- Restructured the mobile login layout so that login tips appear below the form on small screens for better UX.
- Updated related test assertions to ensure correct behavior and layout regressions are caught.
