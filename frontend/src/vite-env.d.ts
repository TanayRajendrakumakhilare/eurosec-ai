/// <reference types="vite/client" />

type EuroSecAPI = {
  selectFolder: () => Promise<string | null>;
  selectFile: () => Promise<string | null>;
};

declare global {
  interface Window {
    eurosec?: EuroSecAPI;
  }
}

export {};
