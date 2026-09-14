import { Box, Typography } from '@mui/material';
import React from 'react';

import { Verification } from '../../types/verification/Verification_Types';

import { VerificationImageComparisonThumbnails } from './VerificationImageComparisonThumbnails';
import { VerificationTextComparisonDisplay } from './VerificationTextComparisonDisplay';

interface VerificationTestResultsProps {
  verification: Verification;
  testResult: Verification;
  processImageUrl: (url: string) => string;
  getCacheBustedUrl: (url: string) => string;
  onImageClick: (
    sourceUrl: string,
    referenceUrl: string,
    overlayUrl?: string,
    userThreshold?: number,
    matchingResult?: number,
    resultType?: 'PASS' | 'FAIL' | 'ERROR',
    imageFilter?: 'none' | 'greyscale' | 'binary',
    focusScore?: number,
    focusThreshold?: number,
  ) => void;
  onSourceImageClick: (
    searchedText: string,
    extractedText: string,
    sourceUrl?: string,
    resultType?: 'PASS' | 'FAIL' | 'ERROR',
    detectedLanguage?: string,
    languageConfidence?: number,
    imageFilter?: 'none' | 'greyscale' | 'binary',
    focusScore?: number,
    focusThreshold?: number,
  ) => void;
}

export const VerificationTestResults: React.FC<VerificationTestResultsProps> = ({
  verification,
  testResult,
  processImageUrl,
  getCacheBustedUrl,
  onImageClick,
  onSourceImageClick,
}) => {
  return (
    <Box sx={{ mt: 0 }}>
      {/* Universal Test Result Status Indicator - shows for ALL verification types */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          minWidth: 120,
          padding: '4px 8px',
          borderRadius: 1,
          mb: 1,
          backgroundColor: testResult.success ? 'rgba(76, 175, 80, 0.1)' : 'rgba(244, 67, 54, 0.1)',
          border: `2px solid ${testResult.success ? '#4caf50' : '#f44336'}`,
        }}
      >
        <Typography
          sx={{
            fontWeight: 'bold',
            fontSize: '0.75rem',
            color: testResult.success ? '#4caf50' : '#f44336',
          }}
        >
          {testResult.success ? 'PASS' : 'FAIL'}
        </Typography>

        {/* Display message within the same status box */}
        {(testResult.message || testResult.error) && (
          <Typography
            sx={{
              fontSize: '0.7rem',
              fontWeight: 500,
              color: testResult.success ? '#4caf50' : '#f44336',
              ml: 1,
            }}
          >
            {testResult.message || testResult.error}
          </Typography>
        )}
      </Box>

      {/* Image comparison thumbnails for image verifications */}
      {verification.verification_type === 'image' &&
        (testResult.sourceImageUrl || testResult.referenceImageUrl) && (
          <VerificationImageComparisonThumbnails
            sourceUrl={testResult.sourceImageUrl || ''}
            referenceUrl={testResult.referenceImageUrl || ''}
            overlayUrl={testResult.resultOverlayUrl}
            resultType={testResult.success ? 'PASS' : 'FAIL'}
            userThreshold={verification.params?.threshold}
            matchingResult={testResult.threshold}
            focusScore={testResult.focusScore}
            focusThreshold={testResult.focusThreshold}
            imageFilter={verification.params?.image_filter || 'none'}
            processImageUrl={processImageUrl}
            getCacheBustedUrl={getCacheBustedUrl}
            onImageClick={onImageClick}
          />
        )}

      {/* Text comparison for text verifications */}
      {verification.verification_type === 'text' &&
        (testResult.searchedText || testResult.sourceImageUrl) && (
          <VerificationTextComparisonDisplay
            searchedText={testResult.searchedText || verification.params?.text || ''}
            extractedText={testResult.extractedText || ''}
            sourceUrl={testResult.sourceImageUrl}
            resultType={testResult.success ? 'PASS' : 'FAIL'}
            detectedLanguage={testResult.detectedLanguage}
            languageConfidence={testResult.languageConfidence}
            focusScore={testResult.focusScore}
            focusThreshold={testResult.focusThreshold}
            onSourceImageClick={onSourceImageClick}
          />
        )}

      {/* Video analysis thumbnail - same pattern as text verification */}
      {verification.verification_type === 'video' && testResult.sourceImageUrl && (
        <VerificationTextComparisonDisplay
          searchedText="Video Analysis"
          extractedText={testResult.message || 'Video analysis completed'}
          sourceUrl={testResult.sourceImageUrl}
          resultType={testResult.success ? 'PASS' : 'FAIL'}
          onSourceImageClick={onSourceImageClick}
        />
      )}
    </Box>
  );
};
