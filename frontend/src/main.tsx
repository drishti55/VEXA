import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './monacoSetup'
import App from './App.tsx'
import { Studio } from './studio/Studio.tsx'

// VEXA Studio is the default UI. The previous single-page dashboard stays available at /?classic
// (or /#classic) until every one of its views has a Studio equivalent.
const classic = new URLSearchParams(window.location.search).has('classic') || window.location.hash === '#classic'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {classic ? <App /> : <Studio />}
  </StrictMode>,
)
