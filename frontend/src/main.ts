import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { showOverflowReport } from './app/core/overflow-debug';

bootstrapApplication(App, appConfig)
  .then(() => showOverflowReport())
  .catch((err) => console.error(err));
