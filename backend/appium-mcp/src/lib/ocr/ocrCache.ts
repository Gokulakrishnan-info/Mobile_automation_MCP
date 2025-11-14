/**
 * Smart caching layer for OCR results
 * Implements LRU cache with TTL to optimize performance
 */

import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as path from 'path';

export interface OCRCacheEntry {
  text: string[];
  boundingBoxes: Array<{ text: string; x: number; y: number; width: number; height: number; confidence: number }>;
  timestamp: number;
  screenshotHash: string;
}

export interface OCRCacheConfig {
  maxSize: number;
  ttl: number; // Time to live in milliseconds
}

export class OCRCache {
  private cache: Map<string, OCRCacheEntry>;
  private config: OCRCacheConfig;
  private accessOrder: string[]; // For LRU eviction

  constructor(config: Partial<OCRCacheConfig> = {}) {
    this.config = {
      maxSize: parseInt(process.env.OCR_CACHE_SIZE || '50', 10),
      ttl: parseInt(process.env.OCR_CACHE_TTL || '300000', 10), // 5 minutes default
      ...config
    };
    this.cache = new Map();
    this.accessOrder = [];
  }

  /**
   * Generate cache key from screenshot path and optional search text
   */
  private generateCacheKey(screenshotPath: string, searchText?: string): string {
    // Use file hash + search text for unique key
    // For now, use file path + modified time as hash approximation
    const key = searchText 
      ? `${screenshotPath}:${searchText}` 
      : screenshotPath;
    return crypto.createHash('md5').update(key).digest('hex');
  }

  /**
   * Calculate file hash for cache key
   */
  private async getFileHash(filePath: string): Promise<string> {
    try {
      const stats = await fs.stat(filePath);
      const content = await fs.readFile(filePath);
      return crypto
        .createHash('md5')
        .update(content)
        .update(stats.mtimeMs.toString())
        .digest('hex');
    } catch (error) {
      // Fallback to path-based key if file read fails
      return crypto.createHash('md5').update(filePath).digest('hex');
    }
  }

  /**
   * Get cached OCR result
   */
  async get(screenshotPath: string, searchText?: string): Promise<OCRCacheEntry | null> {
    const fileHash = await this.getFileHash(screenshotPath);
    const cacheKey = this.generateCacheKey(fileHash, searchText);

    const entry = this.cache.get(cacheKey);
    if (!entry) {
      return null;
    }

    // Check TTL
    const now = Date.now();
    if (now - entry.timestamp > this.config.ttl) {
      this.cache.delete(cacheKey);
      this.removeFromAccessOrder(cacheKey);
      return null;
    }

    // Update access order (move to end)
    this.removeFromAccessOrder(cacheKey);
    this.accessOrder.push(cacheKey);

    return entry;
  }

  /**
   * Store OCR result in cache
   */
  async set(
    screenshotPath: string,
    text: string[],
    boundingBoxes: Array<{ text: string; x: number; y: number; width: number; height: number; confidence: number }>,
    searchText?: string
  ): Promise<void> {
    const fileHash = await this.getFileHash(screenshotPath);
    const cacheKey = this.generateCacheKey(fileHash, searchText);

    // Evict if cache is full (LRU)
    if (this.cache.size >= this.config.maxSize && !this.cache.has(cacheKey)) {
      const oldestKey = this.accessOrder.shift();
      if (oldestKey) {
        this.cache.delete(oldestKey);
      }
    }

    const entry: OCRCacheEntry = {
      text,
      boundingBoxes,
      timestamp: Date.now(),
      screenshotHash: fileHash
    };

    this.cache.set(cacheKey, entry);
    this.removeFromAccessOrder(cacheKey);
    this.accessOrder.push(cacheKey);
  }

  /**
   * Remove key from access order
   */
  private removeFromAccessOrder(key: string): void {
    const index = this.accessOrder.indexOf(key);
    if (index > -1) {
      this.accessOrder.splice(index, 1);
    }
  }

  /**
   * Clear expired entries
   */
  clearExpired(): void {
    const now = Date.now();
    const keysToDelete: string[] = [];

    for (const [key, entry] of this.cache.entries()) {
      if (now - entry.timestamp > this.config.ttl) {
        keysToDelete.push(key);
      }
    }

    for (const key of keysToDelete) {
      this.cache.delete(key);
      this.removeFromAccessOrder(key);
    }
  }

  /**
   * Clear all cache
   */
  clear(): void {
    this.cache.clear();
    this.accessOrder = [];
  }

  /**
   * Get cache statistics
   */
  getStats(): { size: number; maxSize: number; ttl: number } {
    return {
      size: this.cache.size,
      maxSize: this.config.maxSize,
      ttl: this.config.ttl
    };
  }
}

