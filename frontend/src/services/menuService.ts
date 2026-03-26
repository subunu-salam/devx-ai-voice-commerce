import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import {
  DynamoDBDocumentClient,
  ScanCommand,
  QueryCommand,
} from '@aws-sdk/lib-dynamodb';
import type { MenuItem, Category } from '../types';
import { getRuntimeConfig } from '../config';

function getTableName(): string {
  try {
    return getRuntimeConfig().menuTableName;
  } catch {
    return 'DriveThruMenu';
  }
}

function getRegion(): string {
  try {
    return getRuntimeConfig().awsRegion;
  } catch {
    return 'us-east-1';
  }
}

/** Parse a raw DynamoDB item into a MenuItem. */
export function parseMenuItem(item: Record<string, any>): MenuItem {
  const pk: string = item.PK ?? '';
  const sk: string = item.SK ?? '';
  return {
    itemId: sk.replace('ITEM#', ''),
    categoryId: pk.replace('CATEGORY#', ''),
    name: item.name ?? '',
    description: item.description ?? '',
    price: Number(item.price ?? 0),
    imageUrl: item.imageUrl ?? '',
    category: item.category ?? '',
    featured: item.featured === true,
    sortOrder: Number(item.sortOrder ?? 0),
  };
}

/** Parse a raw DynamoDB METADATA item into a Category. */
export function parseCategory(item: Record<string, any>): Category {
  const pk: string = item.PK ?? '';
  return {
    categoryId: pk.replace('CATEGORY#', ''),
    name: item.name ?? '',
    sortOrder: Number(item.sortOrder ?? 0),
  };
}

/** Group a flat list of MenuItems by their categoryId. */
export function groupItemsByCategory(
  items: MenuItem[],
): Record<string, MenuItem[]> {
  const groups: Record<string, MenuItem[]> = Object.create(null) as Record<string, MenuItem[]>;
  for (const item of items) {
    if (!groups[item.categoryId]) {
      groups[item.categoryId] = [];
    }
    groups[item.categoryId].push(item);
  }
  return groups;
}

/** Create a MenuService backed by DynamoDB with the given credentials. */
export function createMenuService(credentials: {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
}) {
  const client = new DynamoDBClient({
    region: getRegion(),
    credentials,
  });
  const docClient = DynamoDBDocumentClient.from(client);
  const tableName = getTableName();

  return {
    /** Scan for all METADATA items to get categories. */
    async getCategories(): Promise<Category[]> {
      try {
        const result = await docClient.send(
          new ScanCommand({
            TableName: tableName,
            FilterExpression: 'SK = :sk',
            ExpressionAttributeValues: { ':sk': 'METADATA' },
          }),
        );
        return (result.Items ?? []).map(parseCategory);
      } catch (err) {
        throw new Error(
          `Menu unavailable. Please try again. (${(err as Error).message})`,
        );
      }
    },

    /** Query items within a specific category. */
    async getItemsByCategory(categoryId: string): Promise<MenuItem[]> {
      try {
        const result = await docClient.send(
          new QueryCommand({
            TableName: tableName,
            KeyConditionExpression: 'PK = :pk AND begins_with(SK, :skPrefix)',
            ExpressionAttributeValues: {
              ':pk': `CATEGORY#${categoryId}`,
              ':skPrefix': 'ITEM#',
            },
          }),
        );
        return (result.Items ?? []).map(parseMenuItem);
      } catch (err) {
        throw new Error(
          `Menu unavailable. Please try again. (${(err as Error).message})`,
        );
      }
    },

    /** Scan for all ITEM# records across all categories. */
    async getAllMenuItems(): Promise<MenuItem[]> {
      try {
        const result = await docClient.send(
          new ScanCommand({
            TableName: tableName,
            FilterExpression: 'begins_with(SK, :skPrefix)',
            ExpressionAttributeValues: { ':skPrefix': 'ITEM#' },
          }),
        );
        return (result.Items ?? []).map(parseMenuItem);
      } catch (err) {
        throw new Error(
          `Menu unavailable. Please try again. (${(err as Error).message})`,
        );
      }
    },
  };
}
