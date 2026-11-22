export default {
  testEnvironment: 'jsdom',
  extensionsToTreatAsEsm: ['.ts', '.tsx'],
  transform: {
    '^.+\\.tsx?$': [
      'ts-jest',
      {
        useESM: true,
        tsconfig: './tsconfig.json',
      },
    ],
  },
  moduleNameMapper: {
    '\\.(css|less|scss)$': '<rootDir>/src/tests/__mocks__/styleMock.ts',
    '^(\\.{1,2}/.*)\\.js$': '$1',
  },
  setupFilesAfterEnv: ['<rootDir>/src/tests/setupTests.ts'],
  testMatch: ['<rootDir>/src/**/*.test.ts', '<rootDir>/src/**/*.test.tsx'],
  collectCoverageFrom: [
    'src/components/**/*.{ts,tsx}',
    'src/routes/**/*.{ts,tsx}',
    'src/api/**/*.{ts,tsx}',
    '!src/api/schema.d.ts',
    '!src/main.tsx',
    '!src/**/*.test.{ts,tsx}',
  ],
  coverageDirectory: '../evidence/coverage/frontend',
  coverageReporters: ['text', 'json-summary', 'lcov'],
  coverageThreshold: {
    global: {
      branches: 91,
      functions: 91,
      lines: 91,
      statements: 91,
    },
  },
};

