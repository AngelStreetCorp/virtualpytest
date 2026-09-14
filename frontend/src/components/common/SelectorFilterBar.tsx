import React from 'react';
import {
  Autocomplete,
  Box,
  Chip,
  InputAdornment,
  TextField,
} from '@mui/material';
import {
  Folder as FolderIcon,
  Search as SearchIcon,
} from '@mui/icons-material';

interface TagOption {
  name: string;
  color: string;
}

interface SelectorFilterBarProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  selectedFolder: string | null;
  onSelectedFolderChange: (value: string | null) => void;
  folderOptions?: string[];
  selectedTags: string[];
  onSelectedTagsChange: (value: string[]) => void;
  tagOptions?: TagOption[];
  searchPlaceholder?: string;
  showSearch?: boolean;
  showFolders?: boolean;
  showTags?: boolean;
  rightContent?: React.ReactNode;
}

export const SelectorFilterBar: React.FC<SelectorFilterBarProps> = ({
  searchQuery,
  onSearchQueryChange,
  selectedFolder,
  onSelectedFolderChange,
  folderOptions = [],
  selectedTags,
  onSelectedTagsChange,
  tagOptions = [],
  searchPlaceholder = 'Search by name...',
  showSearch = true,
  showFolders = true,
  showTags = true,
  rightContent,
}) => (
  <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
    {showSearch && (
      <TextField
        size="small"
        placeholder={searchPlaceholder}
        value={searchQuery}
        onChange={(event) => onSearchQueryChange(event.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
        }}
        sx={{ flex: 1 }}
      />
    )}

    {showFolders && (
      <Autocomplete
        size="small"
        value={selectedFolder}
        onChange={(_event, newValue) => onSelectedFolderChange(newValue)}
        options={['All', ...folderOptions]}
        renderInput={(params) => (
          <TextField
            {...params}
            label="Folder"
            InputProps={{
              ...params.InputProps,
              startAdornment: (
                <>
                  <InputAdornment position="start">
                    <FolderIcon fontSize="small" />
                  </InputAdornment>
                  {params.InputProps.startAdornment}
                </>
              ),
            }}
          />
        )}
        sx={{ flex: 1 }}
      />
    )}

    {showTags && (
      <Autocomplete
        size="small"
        multiple
        value={selectedTags}
        onChange={(_event, newValue) => onSelectedTagsChange(newValue)}
        options={tagOptions.map((tag) => tag.name)}
        disabled={tagOptions.length === 0}
        renderTags={(value, getTagProps) =>
          value.map((option, index) => {
            const tag = tagOptions.find((entry) => entry.name === option);
            return (
              <Chip
                label={option}
                size="small"
                {...getTagProps({ index })}
                sx={{
                  height: '20px',
                  backgroundColor: tag?.color || '#9e9e9e',
                  color: 'white',
                  '& .MuiChip-deleteIcon': {
                    color: 'rgba(255,255,255,0.7)',
                    '&:hover': { color: 'white' },
                  },
                }}
              />
            );
          })
        }
        renderInput={(params) => (
          <TextField
            {...params}
            label="Tags"
            placeholder={selectedTags.length === 0 ? (tagOptions.length === 0 ? 'No tags' : 'None') : 'Filter...'}
          />
        )}
        sx={{ flex: 1 }}
      />
    )}

    {rightContent ? <Box sx={{ flexShrink: 0 }}>{rightContent}</Box> : null}
  </Box>
);
