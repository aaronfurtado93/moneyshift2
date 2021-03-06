import {NgModule} from '@angular/core';
import {ServerModule} from '@angular/platform-server';

import {AppModule} from './app.module';
import {AppComponent} from './app.component';
import {RouterModule, Routes} from '@angular/router';
import {AppShellComponent} from './app-shell/app-shell.component';

const routes: Routes = [ { path: '/', component: AppShellComponent }];

@NgModule({
  imports: [
    AppModule,
    ServerModule,
    RouterModule.forRoot(routes, {
    initialNavigation: 'enabled'
}),
  ],
  bootstrap: [AppComponent],
  declarations: [AppShellComponent],
})
export class AppServerModule {}
