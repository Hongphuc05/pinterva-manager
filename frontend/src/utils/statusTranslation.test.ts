import { describe, it, expect } from 'vitest'
import { resolveExternalUrl, getStatusInfo, getPlatformStatusInfo } from './statusTranslation'

describe('resolveExternalUrl', () => {
  it('returns null for empty, undefined or whitespace inputs', () => {
    expect(resolveExternalUrl(null)).toBeNull()
    expect(resolveExternalUrl(undefined)).toBeNull()
    expect(resolveExternalUrl('')).toBeNull()
    expect(resolveExternalUrl('   ')).toBeNull()
  })

  it('returns null for plain non-URL notes or numbers like "1"', () => {
    expect(resolveExternalUrl('1')).toBeNull()
    expect(resolveExternalUrl('2')).toBeNull()
    expect(resolveExternalUrl('Đã nộp bài')).toBeNull()
    expect(resolveExternalUrl('Xong roi ad oi')).toBeNull()
    expect(resolveExternalUrl('v1.0')).toBeNull()
  })

  it('correctly resolves full http/https URLs', () => {
    expect(resolveExternalUrl('https://drive.google.com/file/d/123/view')).toBe(
      'https://drive.google.com/file/d/123/view'
    )
    expect(resolveExternalUrl('http://dropbox.com/s/xyz')).toBe(
      'http://dropbox.com/s/xyz'
    )
  })

  it('extracts URL if surrounded by text', () => {
    expect(
      resolveExternalUrl('Bài nộp: https://drive.google.com/drive/folders/abc')
    ).toBe('https://drive.google.com/drive/folders/abc')
  })

  it('resolves bare domain URLs without http prefix', () => {
    expect(resolveExternalUrl('drive.google.com/drive/folders/abc')).toBe(
      'https://drive.google.com/drive/folders/abc'
    )
    expect(resolveExternalUrl('canva.com/design/xyz')).toBe(
      'https://canva.com/design/xyz'
    )
  })
})

describe('getStatusInfo & getPlatformStatusInfo', () => {
  it('returns appropriate labels for workflow states', () => {
    expect(getStatusInfo('WAITING').label).toBe('Chờ nhận')
    expect(getStatusInfo('WAITING').description).toBe('Đang chờ được phân công.')
    expect(getStatusInfo('OPEN').label).toBe('Chờ nhận')
    expect(getStatusInfo('DISCOVERED').label).toBe('Chờ nhận')
    expect(getStatusInfo('OPEN_FOR_ALLOCATION').label).toBe('Chờ nhận')
    expect(getStatusInfo('IN_PROGRESS').label).toBe('Đang làm')
    expect(getStatusInfo('QC_PENDING').label).toBe('Chờ duyệt')
    expect(getStatusInfo('REVISION').label).toBe('Cần sửa')
    expect(getStatusInfo('DONE').label).toBe('Hoàn thành')
  })

  it('returns appropriate labels for platform statuses', () => {
    expect(getPlatformStatusInfo('waiting').label).toBe('Waiting')
    expect(getPlatformStatusInfo('doing').label).toBe('Doing')
    expect(getPlatformStatusInfo('review').label).toBe('Review')
    expect(getPlatformStatusInfo('fix').label).toBe('Fix')
    expect(getPlatformStatusInfo(null).label).toBe('Chưa đồng bộ')
  })
})

