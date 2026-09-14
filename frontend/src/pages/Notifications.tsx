import {
  Notifications as NotificationsIcon,
  Email as EmailIcon,
  Chat as SlackIcon,
  Groups as TeamsIcon,
  BugReport as JiraIcon,
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  PlayArrow as TestIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  Schedule as PendingIcon,
  Settings as ConfigIcon,
  Rule as RuleIcon,
  History as HistoryIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  Button,
  Tabs,
  Tab,
  IconButton,
  Tooltip,
} from '@mui/material';
import React, { useState, useEffect } from 'react';

import { useNotifications } from '../hooks/pages/useNotifications';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';

const Notifications: React.FC = () => {
  const {
    integrations,
    rules,
    history,
    deleteIntegration,
    deleteRule,
    testIntegration,
    isLoading,
    error,
  } = useNotifications();

  const [activeTab, setActiveTab] = useState(0);

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Load data on component mount - DISABLED FOR FRONTEND-ONLY VERSION
  useEffect(() => {
    // TODO: Enable when backend is ready
    // const loadData = async () => {
    //   try {
    //     await Promise.all([
    //       loadIntegrations(),
    //       loadRules(),
    //       loadHistory(),
    //     ]);
    //   } catch (err) {
    //     console.error('[@component:Notifications] Error loading data:', err);
    //   }
    // };
    // loadData();
    
    console.log('[@component:Notifications] Frontend-only mode - API calls disabled');
  }, []);

  // Helper functions
  const getIntegrationIcon = (type: string) => {
    switch (type) {
      case 'email':
        return <EmailIcon fontSize="small" />;
      case 'slack':
        return <SlackIcon fontSize="small" />;
      case 'teams':
        return <TeamsIcon fontSize="small" />;
      case 'jira':
        return <JiraIcon fontSize="small" />;
      default:
        return <NotificationsIcon fontSize="small" />;
    }
  };

  const getStatusChip = (status: string) => {
    switch (status) {
      case 'sent':
        return (
          <Chip
            icon={<SuccessIcon />}
            label="Sent"
            color="success"
            size="small"
          />
        );
      case 'failed':
        return (
          <Chip
            icon={<ErrorIcon />}
            label="Failed"
            color="error"
            size="small"
          />
        );
      case 'pending':
        return (
          <Chip
            icon={<PendingIcon />}
            label="Pending"
            color="warning"
            size="small"
          />
        );
      default:
        return (
          <Chip
            label="Unknown"
            color="default"
            size="small"
          />
        );
    }
  };

  const formatDate = (dateString: string): string => {
    return new Date(dateString).toLocaleString();
  };

  const handleTestIntegration = async (id: string, name: string) => {
    try {
      const result = await testIntegration(id);
      // TODO: Show toast notification with result
      console.log(`Test result for ${name}:`, result);
    } catch (err) {
      console.error('Error testing integration:', err);
    }
  };

  const handleDeleteIntegration = async (id: string, name: string) => {
    confirm({
      title: 'Confirm Delete',
      message: `Are you sure you want to delete the integration "${name}"?`,
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await deleteIntegration(id);
          // TODO: Show success toast
        } catch (err) {
          console.error('Error deleting integration:', err);
        }
      },
    });
  };

  const handleDeleteRule = async (id: string, name: string) => {
    confirm({
      title: 'Confirm Delete',
      message: `Are you sure you want to delete the rule "${name}"?`,
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await deleteRule(id);
          // TODO: Show success toast
        } catch (err) {
          console.error('Error deleting rule:', err);
        }
      },
    });
  };

  // Loading state component
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );

  // Integrations Tab Content
  const IntegrationsTab = () => (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">
            Notification Integrations
          </Typography>
          <Button
            startIcon={<AddIcon />}
            variant="contained"
            size="small"
            onClick={() => {
              // TODO: Open create integration dialog
              console.log('Create integration clicked');
            }}
          >
            Add Integration
          </Button>
        </Box>

        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell><strong>Name</strong></TableCell>
                <TableCell><strong>Type</strong></TableCell>
                <TableCell><strong>Status</strong></TableCell>
                <TableCell><strong>Created</strong></TableCell>
                <TableCell><strong>Actions</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <LoadingState />
                  </TableCell>
                </TableRow>
              ) : integrations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} sx={{ textAlign: 'center', py: 4 }}>
                    <Typography variant="body2" color="textSecondary">
                      No integrations configured yet
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                integrations.map((integration) => (
                  <TableRow key={integration.id}>
                    <TableCell>{integration.name}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {getIntegrationIcon(integration.type)}
                        <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                          {integration.type}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={integration.enabled ? 'Enabled' : 'Disabled'}
                        color={integration.enabled ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{formatDate(integration.created_at)}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5 }}>
                        <Tooltip title="Test Integration">
                          <IconButton
                            size="small"
                            onClick={() => handleTestIntegration(integration.id, integration.name)}
                          >
                            <TestIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Edit Integration">
                          <IconButton
                            size="small"
                            onClick={() => {
                              // TODO: Open edit integration dialog
                              console.log('Edit integration:', integration.id);
                            }}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete Integration">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDeleteIntegration(integration.id, integration.name)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );

  // Rules Tab Content
  const RulesTab = () => (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">
            Notification Rules
          </Typography>
          <Button
            startIcon={<AddIcon />}
            variant="contained"
            size="small"
            onClick={() => {
              // TODO: Open create rule dialog
              console.log('Create rule clicked');
            }}
          >
            Add Rule
          </Button>
        </Box>

        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell><strong>Name</strong></TableCell>
                <TableCell><strong>Event Type</strong></TableCell>
                <TableCell><strong>Integrations</strong></TableCell>
                <TableCell><strong>Status</strong></TableCell>
                <TableCell><strong>Created</strong></TableCell>
                <TableCell><strong>Actions</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <LoadingState />
                  </TableCell>
                </TableRow>
              ) : rules.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} sx={{ textAlign: 'center', py: 4 }}>
                    <Typography variant="body2" color="textSecondary">
                      No notification rules configured yet
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell>{rule.name}</TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                        {rule.event_type.replace(/_/g, ' ')}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {rule.integration_ids.length} integration(s)
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={rule.enabled ? 'Enabled' : 'Disabled'}
                        color={rule.enabled ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{formatDate(rule.created_at)}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 0.5 }}>
                        <Tooltip title="Edit Rule">
                          <IconButton
                            size="small"
                            onClick={() => {
                              // TODO: Open edit rule dialog
                              console.log('Edit rule:', rule.id);
                            }}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete Rule">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDeleteRule(rule.id, rule.name)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );

  // History Tab Content
  const HistoryTab = () => (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Notification History
        </Typography>

        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell><strong>Timestamp</strong></TableCell>
                <TableCell><strong>Event Type</strong></TableCell>
                <TableCell><strong>Integration</strong></TableCell>
                <TableCell><strong>Recipient</strong></TableCell>
                <TableCell><strong>Status</strong></TableCell>
                <TableCell><strong>Message Preview</strong></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <LoadingState />
                  </TableCell>
                </TableRow>
              ) : history.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} sx={{ textAlign: 'center', py: 4 }}>
                    <Typography variant="body2" color="textSecondary">
                      No notification history available yet
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                history.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>{formatDate(item.sent_at)}</TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                        {item.event_type.replace(/_/g, ' ')}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {getIntegrationIcon(item.integration_type)}
                        <Typography variant="body2">
                          {item.integration_name}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {item.recipient}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {getStatusChip(item.status)}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ 
                        maxWidth: 200, 
                        overflow: 'hidden', 
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}>
                        {item.message_preview}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );

  return (
    <Box>
      <Box sx={{ mb: 1 }}>
        <Typography variant="h4" gutterBottom>
          Notifications
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => {}}>
          {error}
        </Alert>
      )}

      {/* Quick Stats */}
      <Box sx={{ mb: 0.5 }}>
        <Card>
          <CardContent sx={{ py: 0.5 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={1}>
                <NotificationsIcon color="primary" />
                <Typography variant="h6">Quick Stats</Typography>
              </Box>

              <Box display="flex" alignItems="center" gap={4}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Integrations</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {integrations.length}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Active Rules</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {rules.filter(rule => rule.enabled).length}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Sent Today</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {history.filter(item => {
                      const today = new Date();
                      const itemDate = new Date(item.sent_at);
                      return itemDate.toDateString() === today.toDateString();
                    }).length}
                  </Typography>
                </Box>
              </Box>
            </Box>
          </CardContent>
        </Card>
      </Box>

      {/* Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={activeTab} onChange={(_, newValue) => setActiveTab(newValue)}>
          <Tab 
            icon={<ConfigIcon />} 
            label="Integrations" 
            iconPosition="start"
          />
          <Tab 
            icon={<RuleIcon />} 
            label="Rules" 
            iconPosition="start"
          />
          <Tab 
            icon={<HistoryIcon />} 
            label="History" 
            iconPosition="start"
          />
        </Tabs>
      </Box>

      {/* Tab Content */}
      {activeTab === 0 && <IntegrationsTab />}
      {activeTab === 1 && <RulesTab />}
      {activeTab === 2 && <HistoryTab />}

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default Notifications;
