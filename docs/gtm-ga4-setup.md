# Google Tag Manager + GA4 setup (RankAlpha frontend)

This repo’s Next.js frontend pushes events into `window.dataLayer`. Google Tag Manager (GTM) should listen for those events and forward them to GA4 so reports show real page titles/paths and stock modal interactions.

## Prereqs

- Set `NEXT_PUBLIC_GTM_ID` for the frontend (otherwise it falls back to a shared default container).
- Confirm GTM is loading (view source should include `gtm.js?id=GTM-...`).

## 1) Create / select a GTM Web container

- Use a Web container for the `rankalpha-frontend` site.
- Publish changes only after validating in Preview mode.

## 2) Add a GA4 Configuration tag

1. **Tags → New → Google Analytics: GA4 Configuration**
2. Set **Measurement ID** to your GA4 property (format `G-XXXXXXXXXX`).
3. **Important**: Disable **“Send a page view event when this configuration loads”**.
   - The app already pushes a `page_view` event on route changes; leaving auto pageviews on can double-count.
4. Trigger: **All Pages**

## 3) Track SPA page views (route changes)

The app pushes a `page_view` custom event with these fields:

- `page_title` (uses `document.title`)
- `page_path` (pathname + querystring)
- `page_location` (absolute URL)

### Trigger

1. **Triggers → New → Custom Event**
2. Event name: `page_view`
3. Trigger fires on: **All Custom Events**

### Tag

1. **Tags → New → Google Analytics: GA4 Event**
2. Configuration tag: select the GA4 config tag from step 2
3. Event name: `page_view`
4. Event parameters:
   - `page_title` = `{{DLV - page_title}}`
   - `page_location` = `{{DLV - page_location}}`
   - `page_path` = `{{DLV - page_path}}`
5. Trigger: the `page_view` trigger above

### Data Layer Variables (DLVs)

Create these variables:

- `DLV - page_title` → Data Layer Variable Name: `page_title`
- `DLV - page_location` → Data Layer Variable Name: `page_location`
- `DLV - page_path` → Data Layer Variable Name: `page_path`

## 4) Track stock detail modal opens/closes

The app pushes:

- `stock_detail_open` with: `symbol`, `page_path`, `page_location`
- `stock_detail_close` with: `symbol`, `page_path`, `page_location`

### Triggers

Create two **Custom Event** triggers:

- Event name: `stock_detail_open`
- Event name: `stock_detail_close`

### Tags

Create two **GA4 Event** tags:

- Event name: `stock_detail_open`
  - Parameters:
    - `symbol` = `{{DLV - symbol}}`
    - `page_path` = `{{DLV - page_path}}`
    - `page_location` = `{{DLV - page_location}}`
- Event name: `stock_detail_close`
  - Parameters:
    - `symbol` = `{{DLV - symbol}}`
    - `page_path` = `{{DLV - page_path}}`
    - `page_location` = `{{DLV - page_location}}`

### Data Layer Variable (DLV)

- `DLV - symbol` → Data Layer Variable Name: `symbol`

## 5) Make the modal symbol visible in GA reports (GA4 custom dimensions)

In GA4:

1. **Admin → Custom definitions → Create custom dimension**
2. Scope: **Event**
3. Event parameter: `symbol`
4. Name it e.g. `stock_symbol`

Optional (if you want them in reports as dimensions too):

- `page_path`
- `page_title`

## 6) Verification checklist

- GTM Preview mode shows `page_view` events with a non-generic `page_title` (e.g. `Screener — RankAlpha`, `AI Analysis: AAPL — RankAlpha`).
- GA4 **DebugView** shows:
  - `page_view` firing on navigation
  - `stock_detail_open` firing when the modal opens
  - `stock_detail_close` firing when it closes
- Real-time report shows multiple page titles (not just “RankAlpha”).

## Notes

- If you already have a GA4 “page_view” tag using GTM’s built-in History Change trigger, remove/disable it to avoid duplicate pageviews.
- Private pages like `/admin` and `/portfolio` are marked `noindex` in metadata, but analytics will still track them unless you add filtering rules in GA/GTM.

