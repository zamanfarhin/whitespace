# Whitespace dashboard

Reads `public/leads.json`, which the pipeline writes to `../out/leads.json`.

    cp ../out/leads.json public/
    npm install
    npm run dev          # http://localhost:3000

The UI is a pure consumer of that file. It holds no pipeline logic and needs
no backend, which is why `next build` produces a static site that deploys
anywhere. The score maths in `app/lib.js` mirrors `src/models.py` so the
weight sliders recompute totals the same way the pipeline does.
