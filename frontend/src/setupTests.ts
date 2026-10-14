import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { clearApiCache } from './api/client'

// The in-memory response cache would otherwise leak one test's data into the next.
afterEach(() => clearApiCache())
