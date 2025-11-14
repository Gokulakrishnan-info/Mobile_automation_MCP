/**
 * AWS Bedrock Claude Sonnet Vision OCR Client
 * Extracts text and coordinates from screenshots using Claude Sonnet with vision capabilities
 */

import { BedrockRuntimeClient, InvokeModelCommand } from '@aws-sdk/client-bedrock-runtime';
import * as fs from 'fs/promises';
import { OCRCache, OCRCacheEntry } from './ocrCache.js';

export interface TextBoundingBox {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
}

export interface OCRResult {
  text: string[];
  boundingBoxes: TextBoundingBox[];
  confidence: number;
}

export interface TextCoordinates {
  x: number;
  y: number;
  confidence: number;
}

export class TitanOCR {
  private client: BedrockRuntimeClient;
  private cache: OCRCache;
  private modelId: string;

  constructor(region: string = process.env.AWS_REGION || 'us-east-1') {
    const accessKeyId = process.env.AWS_ACCESS_KEY_ID || '';
    const secretAccessKey = process.env.AWS_SECRET_ACCESS_KEY || '';
    
    // Warn if credentials are missing
    if (!accessKeyId || !secretAccessKey) {
      console.warn('⚠️  AWS credentials not found. Claude Vision OCR will not work. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.');
    }
    
    this.client = new BedrockRuntimeClient({
      region,
      credentials: accessKeyId && secretAccessKey ? {
        accessKeyId,
        secretAccessKey
      } : undefined // Let SDK try to use default credential chain if not provided
    });

    // Use Claude Vision OCR model (default to Haiku for low latency; configurable via env)
    // Haiku handles multimodal input with faster response; switch via CLAUDE_VISION_MODEL_ID when needed.
    this.modelId = process.env.CLAUDE_VISION_MODEL_ID || 'anthropic.claude-3-haiku-20240307-v1:0';
    this.cache = new OCRCache();
    
    console.log(`📝 Claude Vision OCR initialized with model: ${this.modelId}, region: ${region}`);
  }

  /**
   * Extract all text from screenshot with bounding boxes
   * Uses Claude Sonnet with vision capabilities to read text from images
   */
  async extractTextFromScreenshot(screenshotPath: string): Promise<OCRResult> {
    // Check cache first
    const cached = await this.cache.get(screenshotPath);
    if (cached) {
      return {
        text: cached.text,
        boundingBoxes: cached.boundingBoxes,
        confidence: this.calculateAverageConfidence(cached.boundingBoxes)
      };
    }

    try {
      // Read image file
      const imageBuffer = await fs.readFile(screenshotPath);
      const imageBase64 = imageBuffer.toString('base64');
      
      // Detect image format from file extension or buffer
      const imageFormat = screenshotPath.toLowerCase().endsWith('.png') ? 'image/png' : 
                         screenshotPath.toLowerCase().endsWith('.jpg') || screenshotPath.toLowerCase().endsWith('.jpeg') ? 'image/jpeg' :
                         'image/png'; // default to PNG

      // Claude Sonnet vision API format
      const prompt = `Extract ALL visible text from this mobile app screenshot. 
Return a JSON array where each element represents a piece of text found on the screen.
For each text element, provide:
- text: the actual text content
- approximate position: describe where it appears (top-left, top-right, center, bottom, etc.)
- relative position: estimate x and y as percentages (0-100) of screen width/height

Format your response as a valid JSON array:
[{"text": "Login", "x_percent": 50, "y_percent": 20, "position": "center-top", "confidence": 0.95}, ...]

Extract every piece of text you can see, including:
- Button labels
- Field labels
- Headers and titles
- Navigation text
- Any other visible text

Return ONLY the JSON array, no other text.`;

      const requestBody = {
        anthropic_version: "bedrock-2023-05-31",
        max_tokens: 4096,
        messages: [
          {
            role: "user",
            content: [
              {
                type: "image",
                source: {
                  type: "base64",
                  media_type: imageFormat,
                  data: imageBase64
                }
              },
              {
                type: "text",
                text: prompt
              }
            ]
          }
        ]
      };

      const command = new InvokeModelCommand({
        modelId: this.modelId,
        contentType: 'application/json',
        accept: 'application/json',
        body: JSON.stringify(requestBody)
      });

      const response = await this.client.send(command);
      const responseBody = JSON.parse(new TextDecoder().decode(response.body));

      console.log('Claude Vision API response received');
      
      // Parse Claude's response
      const result = this.parseClaudeResponse(responseBody, imageBuffer);
      
      // Log if we got empty results
      if (result.text.length === 0) {
        console.warn('⚠️  Claude Vision OCR returned empty results. Response:', JSON.stringify(responseBody).substring(0, 500));
      } else {
        console.log(`✅ Claude Vision extracted ${result.text.length} text elements`);
      }

      // Cache the result
      await this.cache.set(screenshotPath, result.text, result.boundingBoxes);

      return result;
    } catch (error: any) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      const errorName = error instanceof Error ? error.name : 'UnknownError';
      const errorCode = (error as any)?.$metadata?.httpStatusCode || (error as any)?.code || 'N/A';
      
      console.error('❌ Claude Vision OCR extraction failed:');
      console.error(`   Error Name: ${errorName}`);
      console.error(`   Error Code: ${errorCode}`);
      console.error(`   Error Message: ${errorMessage}`);
      
      // Check for common error types
      if (errorName === 'CredentialsProviderError' || errorMessage.includes('credentials') || errorMessage.includes('Credential')) {
        console.error('⚠️  AWS credentials issue. Verify:');
        console.error('   - AWS_ACCESS_KEY_ID is set');
        console.error('   - AWS_SECRET_ACCESS_KEY is set');
        console.error('   - Credentials have Bedrock permissions');
      } else if (errorMessage.includes('model') || errorMessage.includes('Model') || errorCode === 400 || errorCode === 403) {
        console.error('⚠️  Model access issue. Check:');
        console.error(`   - Model "${this.modelId}" is enabled in your AWS Bedrock account`);
        console.error('   - Your AWS account has access to Claude models');
        console.error('   - Region supports this model');
        console.error('   - Go to AWS Console → Bedrock → Model access → Request access to Claude models');
      } else if (errorMessage.includes('region') || errorMessage.includes('Region') || errorMessage.includes('endpoint')) {
        console.error('⚠️  AWS region issue. Check:');
        console.error('   - AWS_REGION is set correctly');
        console.error('   - Region supports Bedrock service');
      } else if (errorMessage.includes('ValidationException') || errorMessage.includes('Invalid')) {
        console.error('⚠️  API request format issue. Check:');
        console.error('   - Image format is supported (PNG, JPEG)');
        console.error('   - Image size is within limits');
        console.error('   - Request body format is correct');
      }
      
      // Log full error details for debugging
      if (error instanceof Error && error.stack) {
        console.error('   Stack trace:', error.stack.substring(0, 300));
      }
      
      // Fallback: Return empty result with low confidence
      // Note: This allows the system to continue but OCR features won't work
      return {
        text: [],
        boundingBoxes: [],
        confidence: 0.0
      };
    }
  }

  /**
   * Find coordinates of specific text in screenshot
   */
  async findTextCoordinates(screenshotPath: string, searchText: string): Promise<TextCoordinates | null> {
    // Check cache with search text
    const cached = await this.cache.get(screenshotPath, searchText);
    if (cached) {
      const matchingBox = cached.boundingBoxes.find(
        box => box.text.toLowerCase().includes(searchText.toLowerCase())
      );
      if (matchingBox) {
        return {
          x: matchingBox.x + Math.floor(matchingBox.width / 2),
          y: matchingBox.y + Math.floor(matchingBox.height / 2),
          confidence: matchingBox.confidence
        };
      }
    }

    // Extract all text
    const ocrResult = await this.extractTextFromScreenshot(screenshotPath);

    // Search for the text
    const matchingBox = ocrResult.boundingBoxes.find(
      box => box.text.toLowerCase().includes(searchText.toLowerCase())
    );

    if (matchingBox) {
      // Return center coordinates with small random offset to avoid exact center
      const offsetX = Math.floor(Math.random() * 10) - 5; // -5 to +5
      const offsetY = Math.floor(Math.random() * 10) - 5;
      
      return {
        x: matchingBox.x + Math.floor(matchingBox.width / 2) + offsetX,
        y: matchingBox.y + Math.floor(matchingBox.height / 2) + offsetY,
        confidence: matchingBox.confidence
      };
    }

    return null;
  }

  /**
   * Parse Claude Sonnet vision response into OCR result
   * Claude returns text in content blocks, we extract and parse the JSON response
   */
  private parseClaudeResponse(responseBody: any, imageBuffer: Buffer): OCRResult {
    try {
      // Claude response format: { content: [{ type: "text", text: "..." }] }
      const content = responseBody.content || [];
      let textResponse = '';
      
      // Extract text from all content blocks
      for (const block of content) {
        if (block.type === 'text' && block.text) {
          textResponse += block.text;
        }
      }
      
      if (!textResponse) {
        console.warn('Claude response has no text content');
        return this.fallbackOCR(imageBuffer);
      }
      
      // Try to extract JSON array from the response
      // Claude might wrap the JSON in markdown code blocks or plain text
      let jsonText = textResponse.trim();
      
      // Remove markdown code blocks if present
      jsonText = jsonText.replace(/```json\n?/g, '').replace(/```\n?/g, '');
      jsonText = jsonText.replace(/```\n?/g, '');
      
      // Try to find JSON array in the response
      const jsonMatch = jsonText.match(/\[[\s\S]*\]/);
      if (jsonMatch) {
        jsonText = jsonMatch[0];
      }
      
      // Parse the JSON
      const elements = JSON.parse(jsonText);
      
      if (!Array.isArray(elements)) {
        console.warn('Claude response is not a JSON array');
        return this.fallbackOCR(imageBuffer);
      }
      
      // Convert percentage-based coordinates to pixel coordinates
      // We'll use a default screen size (1080x1920 for mobile) and convert percentages
      const defaultWidth = 1080;
      const defaultHeight = 1920;
      
      const boundingBoxes: TextBoundingBox[] = elements.map((elem: any) => {
        const xPercent = elem.x_percent || elem.x || 50;
        const yPercent = elem.y_percent || elem.y || 50;
        
        // Convert percentages to pixel coordinates
        const x = Math.floor((xPercent / 100) * defaultWidth);
        const y = Math.floor((yPercent / 100) * defaultHeight);
        
        // Estimate width and height based on text length
        // Rough estimate: ~10 pixels per character, ~30 pixels height
        const textLength = (elem.text || '').length;
        const width = Math.max(50, Math.min(400, textLength * 10));
        const height = 30;
        
        return {
          text: elem.text || elem.label || '',
          x: x - Math.floor(width / 2), // Center the box on the x coordinate
          y: y - Math.floor(height / 2), // Center the box on the y coordinate
          width,
          height,
          confidence: elem.confidence || 0.9 // Claude is generally very accurate
        };
      });

      return {
        text: boundingBoxes.map(box => box.text),
        boundingBoxes,
        confidence: this.calculateAverageConfidence(boundingBoxes)
      };
    } catch (error: any) {
      console.error('Error parsing Claude response:', error);
      console.error('Response body:', JSON.stringify(responseBody).substring(0, 500));
      return this.fallbackOCR(imageBuffer);
    }
  }

  /**
   * Fallback OCR when Claude fails
   * Returns empty result - system will continue with XML-only mode
   */
  private fallbackOCR(imageBuffer: Buffer): OCRResult {
    console.warn('Using fallback OCR - Claude Vision extraction failed, returning empty result');
    
    return {
      text: [],
      boundingBoxes: [],
      confidence: 0.0
    };
  }

  /**
   * Calculate average confidence from bounding boxes
   */
  private calculateAverageConfidence(boxes: TextBoundingBox[]): number {
    if (boxes.length === 0) return 0.0;
    const sum = boxes.reduce((acc, box) => acc + box.confidence, 0);
    return sum / boxes.length;
  }

  /**
   * Clear OCR cache
   */
  clearCache(): void {
    this.cache.clear();
  }

  /**
   * Get cache statistics
   */
  getCacheStats() {
    return this.cache.getStats();
  }
}

