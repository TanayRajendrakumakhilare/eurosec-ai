export {};

declare global {
  interface Window {
    eurosec?: {
      selectFolder: () => Promise<string | null>;
      selectFile: () => Promise<string | null>;
    };
  }
}
