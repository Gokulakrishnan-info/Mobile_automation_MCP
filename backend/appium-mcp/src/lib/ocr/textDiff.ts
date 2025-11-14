/**
 * Text diff algorithm for verifying screen changes
 * Calculates similarity score between before/after OCR text arrays
 */

export interface TextDiffResult {
  similarity: number; // 0-1 score (1 = identical, 0 = completely different)
  added: string[];
  removed: string[];
  unchanged: string[];
  keywordsFound: string[];
  keywordsMissing: string[];
}

export class TextDiff {
  /**
   * Calculate text difference between two OCR text arrays
   */
  calculateTextDiff(beforeTexts: string[], afterTexts: string[]): TextDiffResult {
    // Normalize texts (lowercase, trim)
    const before = this.normalizeTexts(beforeTexts);
    const after = this.normalizeTexts(afterTexts);

    // Find added, removed, and unchanged texts
    const beforeSet = new Set(before);
    const afterSet = new Set(after);

    const added = after.filter(text => !beforeSet.has(text));
    const removed = before.filter(text => !afterSet.has(text));
    const unchanged = before.filter(text => afterSet.has(text));

    // Calculate similarity using Jaccard similarity
    const intersection = unchanged.length;
    const union = new Set([...before, ...after]).size;
    const similarity = union > 0 ? intersection / union : 0;

    return {
      similarity,
      added,
      removed,
      unchanged,
      keywordsFound: [],
      keywordsMissing: []
    };
  }

  /**
   * Verify action with expected keywords
   */
  verifyAction(
    expectedKeywords: string[],
    beforeTexts: string[],
    afterTexts: string[]
  ): { success: boolean; diff_score: number; keywords_found: string[]; keywords_missing: string[] } {
    const diff = this.calculateTextDiff(beforeTexts, afterTexts);
    
    // Check for expected keywords in after text
    const afterNormalized = this.normalizeTexts(afterTexts);
    const expectedNormalized = this.normalizeTexts(expectedKeywords);
    
    const keywordsFound: string[] = [];
    const keywordsMissing: string[] = [];

    for (const keyword of expectedNormalized) {
      // Check if keyword appears in any of the after texts (partial match)
      const found = afterNormalized.some(text => 
        text.includes(keyword) || keyword.includes(text)
      );
      
      if (found) {
        keywordsFound.push(keyword);
      } else {
        keywordsMissing.push(keyword);
      }
    }

    // Determine success based on thresholds
    const threshold = parseFloat(process.env.TEXT_DIFF_THRESHOLD || '0.3');
    const success = diff.similarity > threshold && keywordsMissing.length === 0;

    return {
      success,
      diff_score: diff.similarity,
      keywords_found: keywordsFound,
      keywords_missing: keywordsMissing
    };
  }

  /**
   * Normalize text array (lowercase, trim, remove empty)
   */
  private normalizeTexts(texts: string[]): string[] {
    return texts
      .map(text => text.toLowerCase().trim())
      .filter(text => text.length > 0);
  }

  /**
   * Calculate similarity score with fuzzy matching
   * Uses Levenshtein distance for partial matches
   */
  calculateFuzzySimilarity(text1: string, text2: string): number {
    const normalized1 = text1.toLowerCase().trim();
    const normalized2 = text2.toLowerCase().trim();

    if (normalized1 === normalized2) return 1.0;
    if (normalized1.includes(normalized2) || normalized2.includes(normalized1)) return 0.8;

    // Simple Levenshtein distance calculation
    const distance = this.levenshteinDistance(normalized1, normalized2);
    const maxLength = Math.max(normalized1.length, normalized2.length);
    
    return maxLength > 0 ? 1 - (distance / maxLength) : 0;
  }

  /**
   * Calculate Levenshtein distance between two strings
   */
  private levenshteinDistance(str1: string, str2: string): number {
    const matrix: number[][] = [];

    for (let i = 0; i <= str2.length; i++) {
      matrix[i] = [i];
    }

    for (let j = 0; j <= str1.length; j++) {
      matrix[0][j] = j;
    }

    for (let i = 1; i <= str2.length; i++) {
      for (let j = 1; j <= str1.length; j++) {
        if (str2.charAt(i - 1) === str1.charAt(j - 1)) {
          matrix[i][j] = matrix[i - 1][j - 1];
        } else {
          matrix[i][j] = Math.min(
            matrix[i - 1][j - 1] + 1,
            matrix[i][j - 1] + 1,
            matrix[i - 1][j] + 1
          );
        }
      }
    }

    return matrix[str2.length][str1.length];
  }
}

