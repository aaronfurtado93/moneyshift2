export interface IPlayer {
  _id?: string;
  name: {
    first: string;
    middle?: string;
    last: string;
  };
  balance?: number;
  dates?: {
    created: {
      dateTime: string;
      by: string;
    };
    updated: {
      dateTime: string;
      by: string;
    };
    deleted: {
      dateTime: string;
      by: string;
    };
  };
  isActive: boolean;
}
