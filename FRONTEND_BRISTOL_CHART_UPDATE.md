# Frontend Bristol Stool Chart update

- Added the supplied `Bristol Stool Chart Infographic.png` asset.
- Added `GET /bristol-stool-chart.png` to serve the image from FastAPI.
- Updated `index.html` to render `[[BRISTOL_STOOL_CHART]]` as the chart image before the Bristol type explanations and question.
- The image is inserted using DOM APIs; backend response text is not interpreted as arbitrary HTML.
- The Shopify widget already has its own embedded Bristol chart handling in `gutgpt-widget.js`; this change adds the same chart support to the standalone browser frontend.
