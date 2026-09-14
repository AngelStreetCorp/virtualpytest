import React from 'react';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';

export const NavigationBreadcrumb: React.FC = () => {
  const { breadcrumb, jumpToLevel, jumpToRoot, isNested, depth } = useNavigationStack();

  if (!isNested || breadcrumb.length === 0) {
    return null;
  }

  return (
    <div className="navigation-breadcrumb bg-gray-100 border-b border-gray-200 px-4 py-2 flex items-center space-x-2 text-sm">
      <button 
        onClick={jumpToRoot}
        className="breadcrumb-item root flex items-center px-2 py-1 rounded hover:bg-gray-200 transition-colors"
      >
        <span className="mr-1">🏠</span>
        Root
      </button>
      
      {breadcrumb.map((item, index) => (
        <React.Fragment key={item.tree_id}>
          <span className="breadcrumb-separator text-gray-400">›</span>
          <button
            onClick={() => jumpToLevel(index)}
            className={`breadcrumb-item px-2 py-1 rounded transition-colors ${
              index === breadcrumb.length - 1 
                ? 'current bg-blue-100 text-blue-800 font-medium' 
                : 'hover:bg-gray-200 text-gray-700'
            }`}
          >
            {item.tree_name}
          </button>
        </React.Fragment>
      ))}
      
      <div className="breadcrumb-info ml-auto flex items-center text-xs text-gray-500">
        <span className="mr-2">Depth: {depth}/5</span>
        {depth >= 4 && (
          <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded">
            Near limit
          </span>
        )}
        {depth >= 5 && (
          <span className="px-2 py-1 bg-red-100 text-red-800 rounded">
            Max depth
          </span>
        )}
      </div>
    </div>
  );
};
