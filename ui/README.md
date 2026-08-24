# ui

Vite configurator on `:5173`. It does not draw the courtyard. The start scripts do not launch this.

```
browser  :5173
   /api          →  ovrtx    127.0.0.1:8791
   /physics      →  ovphysx  127.0.0.1:8793
```

| Call | Process | Role |
| --- | --- | --- |
| `GET /api/frame.jpg` | ovrtx | Viewport |
| `GET /api/status` | ovrtx | Live / first-frame |
| `POST /api/control` | ovrtx | Finish, light, rider, camera, ride |
| `GET /physics/api/status` | ovphysx | rpm from omega; remaining useful life is `1 - wear` |
| `POST /physics/api/control` | ovphysx | `{ riding }` |

On the Brev host, after the two servers and the host proxy:

```bash
cd /tmp/cudacycle/ui
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. On a laptop, tunnel `:8791` and `:8793` or `/api` is 502 and the viewport stays blank.
