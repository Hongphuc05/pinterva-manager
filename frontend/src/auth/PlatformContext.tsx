import React, { createContext, useContext, useState, useEffect } from 'react'
import { apiFetch } from '../api/client'
import { useAuth } from './AuthContext'

export interface Platform {
  id: string
  name: string
  account_username: string
  team_outsource?: string
  is_active: boolean
  created_at: string
}

interface PlatformContextType {
  platforms: Platform[]
  activePlatform: Platform | null
  setActivePlatform: (p: Platform) => void
  refreshPlatforms: () => Promise<void>
  createPlatform: (name: string, accountUsername: string) => Promise<Platform>
  isLoading: boolean
}

const PlatformContext = createContext<PlatformContextType | undefined>(undefined)

export const PlatformProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isAdmin } = useAuth()
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [activePlatform, setActivePlatformState] = useState<Platform | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)

  const setActivePlatform = (platform: Platform) => {
    setActivePlatformState(platform)
    localStorage.setItem('activePlatformId', platform.id)
    // Trigger page reload or re-fetch to ensure clean state scoping across active pages
    window.location.reload()
  }

  const refreshPlatforms = async () => {
    if (!user || !isAdmin) return
    setIsLoading(true)
    try {
      const list = await apiFetch<Platform[]>('/platforms')
      if (Array.isArray(list)) {
        setPlatforms(list)

        const savedId = localStorage.getItem('activePlatformId')
        let matched = list.find((p) => p.id === savedId)
        if (!matched && list.length > 0) {
          matched = list[0]
        }
        if (matched) {
          setActivePlatformState(matched)
          localStorage.setItem('activePlatformId', matched.id)
        }
      }
    } catch (err) {
      console.error('Failed to fetch platforms:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const createPlatform = async (name: string, accountUsername: string): Promise<Platform> => {
    const created = await apiFetch<Platform>('/platforms', {
      method: 'POST',
      body: JSON.stringify({ name, account_username: accountUsername }),
    })
    await refreshPlatforms()
    setActivePlatform(created)
    return created
  }

  useEffect(() => {
    if (user && isAdmin) {
      refreshPlatforms()
    }
  }, [user, isAdmin])

  return (
    <PlatformContext.Provider
      value={{
        platforms,
        activePlatform,
        setActivePlatform,
        refreshPlatforms,
        createPlatform,
        isLoading,
      }}
    >
      {children}
    </PlatformContext.Provider>
  )
}

export const usePlatform = () => {
  const context = useContext(PlatformContext)
  if (!context) {
    throw new Error('usePlatform must be used within a PlatformProvider')
  }
  return context
}
