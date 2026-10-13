import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Chip,
  OutlinedInput,
  SelectChangeEvent,
  Checkbox,
  ListItemText,
} from '@mui/material';
import React, { useState } from 'react';

// Import the simplified interface from Models.tsx
import { ModelCreatePayload as ModelCreateData } from '../../types/pages/Models_Types';
import { StyledDialog } from '../common/StyledDialog';

interface CreateModelDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (model: ModelCreateData) => void;
  error?: string | null;
  // Names a host can run that this team has no row for yet
  availableNames: string[];
}

const modelTypes = [
  'Android Mobile',
  'Android TV',
  'Android Tablet',
  'iOs Phone',
  'iOs Tablet',
  'Fire TV',
  'Nvidia Shield',
  'Apple TV',
  'STB',
  'Linux',
  'Windows',
  'Desktop',
  'Camera',
  'Tizen TV',
  'LG TV',
];

const ITEM_HEIGHT = 48;
const ITEM_PADDING_TOP = 8;
const MenuProps = {
  PaperProps: {
    style: {
      maxHeight: ITEM_HEIGHT * 4.5 + ITEM_PADDING_TOP,
      width: 250,
    },
  },
};

const CreateModelDialog: React.FC<CreateModelDialogProps> = ({
  open,
  onClose,
  onSubmit,
  availableNames,
}) => {
  const [formData, setFormData] = useState<ModelCreateData>({
    name: '',
    types: [],
    version: '',
    description: '',
  });

  const handleClose = () => {
    setFormData({
      name: '',
      types: [],
      version: '',
      description: '',
    });
    onClose();
  };

  const handleSubmit = () => {
    onSubmit(formData);
  };

  const handleTypeChange = (event: SelectChangeEvent<string[]>) => {
    const value = event.target.value;
    setFormData({
      ...formData,
      types: typeof value === 'string' ? value.split(',') : value,
    });
  };

  const handleInputChange =
    (field: keyof ModelCreateData) => (event: React.ChangeEvent<HTMLInputElement>) => {
      setFormData({
        ...formData,
        [field]: event.target.value,
      });
    };

  return (
    <StyledDialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ pb: 1 }}>Add New Device Model</DialogTitle>
      <DialogContent sx={{ pt: 1 }}>
        <Box sx={{ pt: 0.5 }}>
          {/* The name is what a host's DEVICE{i}_MODEL must say, so only models a host can run */}
          <FormControl fullWidth margin="dense" sx={{ mb: 1.5 }} required>
            <InputLabel size="small">Name</InputLabel>
            <Select
              size="small"
              value={formData.name}
              onChange={(event: SelectChangeEvent<string>) =>
                setFormData({ ...formData, name: event.target.value })
              }
              input={<OutlinedInput label="Name" />}
              MenuProps={MenuProps}
            >
              {availableNames.length === 0 ? (
                <MenuItem disabled value="">
                  Every model a host can run is already listed
                </MenuItem>
              ) : (
                availableNames.map((name) => (
                  <MenuItem key={name} value={name}>
                    {name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>

          <FormControl fullWidth margin="dense" sx={{ mb: 1.5 }}>
            <InputLabel size="small">Types *</InputLabel>
            <Select
              multiple
              size="small"
              value={formData.types}
              onChange={handleTypeChange}
              input={<OutlinedInput label="Types *" />}
              renderValue={(selected) => (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {selected.map((value) => (
                    <Chip key={value} label={value} size="small" />
                  ))}
                </Box>
              )}
              MenuProps={MenuProps}
            >
              {modelTypes.map((type) => (
                <MenuItem key={type} value={type}>
                  <Checkbox checked={formData.types.indexOf(type) > -1} />
                  <ListItemText primary={type} />
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            margin="dense"
            label="Version"
            fullWidth
            variant="outlined"
            value={formData.version}
            onChange={handleInputChange('version')}
            sx={{ mb: 1.5 }}
            size="small"
            placeholder="e.g., 12.0, Android 11"
          />

          <TextField
            margin="dense"
            label="Description"
            fullWidth
            variant="outlined"
            value={formData.description}
            onChange={handleInputChange('description')}
            size="small"
            placeholder="Additional specifications or notes"
          />
        </Box>
      </DialogContent>
      <DialogActions sx={{ pt: 1, pb: 2 }}>
        <Button onClick={handleClose} size="small">
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          size="small"
          disabled={!formData.name || formData.types.length === 0}
        >
          Add Model
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

export default CreateModelDialog;
export { CreateModelDialog };
