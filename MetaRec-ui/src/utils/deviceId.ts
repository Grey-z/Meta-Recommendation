/**
 * 设备ID管理工具
 * 为每个访问设备生成并存储唯一的设备ID
 */

const DEVICE_ID_KEY = 'metarec_device_id'

/**
 * 生成唯一的设备ID
 */
function generateDeviceId(): string {
  // 使用时间戳 + 随机数生成ID
  const timestamp = Date.now()
  const random = Math.random().toString(36).substring(2, 15)
  return `device_${timestamp}_${random}`
}

/**
 * 获取或创建设备ID
 * 如果localStorage中已有设备ID，则返回它
 * 否则生成新的设备ID并存储
 */
export function getDeviceId(): string {
  try {
    // 尝试从localStorage获取
    let deviceId = localStorage.getItem(DEVICE_ID_KEY)
    
    if (!deviceId) {
      // 如果没有，生成新的
      deviceId = generateDeviceId()
      localStorage.setItem(DEVICE_ID_KEY, deviceId)
    }
    
    return deviceId
  } catch (error) {
    // 如果localStorage不可用（如隐私模式），使用sessionStorage
    console.warn('localStorage not available, using sessionStorage:', error)
    try {
      let deviceId = sessionStorage.getItem(DEVICE_ID_KEY)
      
      if (!deviceId) {
        deviceId = generateDeviceId()
        sessionStorage.setItem(DEVICE_ID_KEY, deviceId)
      }
      
      return deviceId
    } catch (e) {
      // 如果都不可用，生成临时ID（会话期间有效）
      console.warn('sessionStorage not available, using temporary ID:', e)
      return generateDeviceId()
    }
  }
}

/**
 * 清除设备ID（用于测试或重置）
 */
export function clearDeviceId(): void {
  try {
    localStorage.removeItem(DEVICE_ID_KEY)
    sessionStorage.removeItem(DEVICE_ID_KEY)
  } catch (error) {
    console.warn('Failed to clear device ID:', error)
  }
}

